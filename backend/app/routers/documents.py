"""
文档管理路由
"""
import os
import json
import uuid
from datetime import datetime
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, BackgroundTasks, Query, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session
from typing import List
from ..database import get_db
from ..pagination import paginate
from ..dependencies import verify_admin, limit_upload, get_admin_password

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ..models import Document, ClassicText, MedicalCase, ImportBatch, ImportStaging
from ..schemas import DocumentResponse, MessageResponse
from ..logger import get_logger
from ..services.parser import DocumentParser

logger = get_logger(__name__)
from ..services.import_validator import validate_import_batch, format_report_text

router = APIRouter()

# 上传目录（与 DATA_DIR 保持一致，支持云平台持久磁盘）
_DATA_ROOT = os.environ.get("DATA_DIR", BASE_DIR)
UPLOAD_DIR = os.path.join(_DATA_ROOT, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


def process_document(doc_id: int, file_path: str):
    """
    后台处理文档：解析 → 质检 → 暂存 → 等待人工审核发布。

    不再直接写入 classic_texts。解析结果先进 import_staging，
    管理员通过 /api/import/batches/{batch_id}/publish 确认后发布。
    """
    from ..database import SessionLocal
    db = SessionLocal()
    try:
        doc = db.query(Document).filter(Document.id == doc_id).first()
        if not doc:
            return

        doc.status = "processing"
        doc.error_message = None
        db.commit()

        # ── 解析文档 ──
        parser = DocumentParser(UPLOAD_DIR)
        parse_result = parser.parse(file_path, doc.file_type)
        content = parse_result.get("content", "") or ""
        paragraphs = parse_result.get("paragraphs")
        source_hash = parse_result.get("sha256", "")
        source_file = doc.filename

        # ── 句末条号收束切分 ──
        extracted = parser.extract_texts_and_cases(
            content, filename=source_file, paragraphs=paragraphs,
        )

        doc.parsed_content = content[:50000]
        doc.processed_at = datetime.now()
        db.commit()

        texts = extracted.get("texts", [])
        if not texts or len(texts) < 3:
            doc.status = "failed"
            doc.error_message = f"解析失败：仅提取到 {len(texts)} 条条文（预期 ≥3）"
            db.commit()
            return

        # ── 质量闸门 ──
        source_book = texts[0].get("source_book", "《伤寒论》") if texts else "《伤寒论》"
        quality_report = validate_import_batch(texts, expected_book=source_book)
        logger.info("质检报告:\n%s", format_report_text(quality_report))

        # ── 创建导入批次 ──
        batch_id = uuid.uuid4().hex[:12]
        batch = ImportBatch(
            batch_id=batch_id,
            source_file=source_file,
            source_hash=source_hash,
            source_edition=None,
            total_articles=len(texts),
            unique_numbers=quality_report["actual_unique"],
            status="needs_review",
            quality_report=json.dumps(quality_report, ensure_ascii=False),
        )
        db.add(batch)
        db.commit()

        # ── 写入暂存区 ──
        duplicates = quality_report.get("duplicates", {})
        num_first_seen = set()
        staged_count = 0
        for art in texts:
            num = art.get("article_number")
            status = "needs_review"
            issue = None

            if num in duplicates:
                if num in num_first_seen:
                    issue = f"duplicate: 条号 {num} 重复出现，需人工裁决"
                else:
                    num_first_seen.add(num)

            stg = ImportStaging(
                batch_id=batch_id,
                source_book=art.get("source_book", source_book),
                chapter=art.get("chapter"),
                section=art.get("section"),
                article_number=num,
                order_index=num,
                raw_content=art.get("raw_content", ""),
                content=art.get("content", ""),
                layout_marker=art.get("layout_marker"),
                source_file=source_file,
                source_hash=source_hash,
                source_offset=art.get("source_offset"),
                source_edition=None,
                status=status,
                issue=issue,
            )
            db.add(stg)
            staged_count += 1

        db.commit()

        doc.status = "completed"
        doc.parsed_content = content[:50000]
        db.commit()

        passed = quality_report.get("passed", False)
        logger.info(
            "完成: 暂存 %s 条, 批次 %s, 质检 %s",
            staged_count, batch_id, '通过' if passed else '待审核'
        )
        if quality_report.get("issues"):
            logger.warning("质量问题: %s", quality_report['issues'])

    except Exception as e:
        import traceback
        traceback.print_exc()
        db.rollback()
        doc = db.query(Document).filter(Document.id == doc_id).first()
        if doc:
            doc.status = "failed"
            doc.error_message = str(e)[:1000]
            doc.processed_at = datetime.now()
            db.commit()
        logger.exception("文档处理失败")
    finally:
        db.close()


# 文件上传大小限制
MAX_UPLOAD_NORMAL = 20 * 1024 * 1024    # 20MB，无需额外验证
MAX_UPLOAD_HARD   = 200 * 1024 * 1024   # 200MB，绝对上限

# 允许的扩展名白名单（用于落盘文件名，防止路径穿越与可执行文件上传）
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".doc", ".xlsx", ".xls", ".txt"}


@router.post("/upload", response_model=MessageResponse, summary="上传文档")
async def upload_document(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin),
    _rl: None = Depends(limit_upload),
):
    """上传文档，支持 PDF、Word、TXT、Excel，后台自动解析并暂存到审核区。

    大小限制：
    - ≤ 20MB：直接上传
    - 20MB ~ 200MB：需在请求头 `X-Upload-Password` 中附加管理员密码
    - > 200MB：拒绝
    """
    import secrets as _secrets

    # 1. 检查文件大小（优先从 Content-Length 获取）
    content_length = request.headers.get("content-length")
    upload_size = getattr(file, "size", None)
    if isinstance(upload_size, int):
        file_size_hint = upload_size
    elif content_length:
        try:
            file_size_hint = int(content_length)
        except ValueError:
            file_size_hint = None
    else:
        file_size_hint = None

    # 硬上限
    if file_size_hint and file_size_hint > MAX_UPLOAD_HARD:
        raise HTTPException(
            status_code=413,
            detail=f"文件过大（{file_size_hint / 1024 / 1024:.1f}MB），最大允许 {MAX_UPLOAD_HARD // 1024 // 1024}MB"
        )

    # 分级验证：> 20MB 需要额外密码
    if file_size_hint and file_size_hint > MAX_UPLOAD_NORMAL:
        upload_password = request.headers.get("X-Upload-Password", "")
        correct = get_admin_password()
        if not correct or not _secrets.compare_digest(upload_password.encode(), correct.encode()):
            raise HTTPException(
                status_code=401,
                detail=f"文件超过 20MB（{file_size_hint / 1024 / 1024:.1f}MB），"
                       f"请在请求头 X-Upload-Password 中提供管理员密码"
            )

    # 2. 检查文件类型
    allowed_types = [
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-excel",
        "text/plain"
    ]

    if file.content_type not in allowed_types and not any(
        file.filename.lower().endswith(ext)
        for ext in ['.pdf', '.docx', '.doc', '.xlsx', '.xls', '.txt']
    ):
        raise HTTPException(
            status_code=400,
            detail="不支持的文件类型，仅支持PDF、Word、Excel、TXT格式"
        )

    # 3. 生成唯一文件名：只取 basename + 扩展名白名单，原始名不参与路径拼接
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    original_name = Path(file.filename or "").name
    suffix = Path(original_name).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件扩展名 {suffix or '(无)'}，"
                   f"仅支持 {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )
    safe_filename = f"{timestamp}_{uuid.uuid4().hex[:8]}{suffix}"
    file_path = os.path.join(UPLOAD_DIR, safe_filename)
    display_name = original_name or safe_filename

    # 4. 流式保存（同时检查实际大小，防止 Content-Length 伪造绕过）
    try:
        bytes_written = 0
        with open(file_path, "wb") as buffer:
            while chunk := file.file.read(1024 * 1024):  # 1MB chunks
                bytes_written += len(chunk)
                if bytes_written > MAX_UPLOAD_HARD:
                    buffer.close()
                    os.unlink(file_path)
                    raise HTTPException(
                        status_code=413,
                        detail=f"文件实际大小超过 {MAX_UPLOAD_HARD // 1024 // 1024}MB 上限"
                    )
                # 如果未提供 Content-Length 且超过 20MB，中途拦截
                if not content_length and bytes_written > MAX_UPLOAD_NORMAL:
                    upload_password = request.headers.get("X-Upload-Password", "")
                    correct = get_admin_password()
                    if not correct or not _secrets.compare_digest(upload_password.encode(), correct.encode()):
                        buffer.close()
                        os.unlink(file_path)
                        raise HTTPException(
                            status_code=401,
                            detail="文件超过 20MB，请在请求头 X-Upload-Password 中提供管理员密码"
                        )
                buffer.write(chunk)
        file_size = bytes_written
    except HTTPException:
        raise
    except Exception as e:
        if os.path.exists(file_path):
            os.unlink(file_path)
        raise HTTPException(status_code=500, detail=f"文件保存失败: {str(e)}")

    # 5. 保存文件信息到数据库
    doc = Document(
        filename=display_name,
        file_type=file.content_type or "unknown",
        file_path=file_path,
        file_size=file_size,
        status="pending"
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    # 6. 后台处理文档（解析→质检→暂存）
    background_tasks.add_task(process_document, doc.id, file_path)

    return MessageResponse(
        message=f"文件 {display_name}（{file_size / 1024 / 1024:.1f}MB）上传成功，正在后台解析并暂存至审核区...",
        success=True
    )


@router.delete("/{doc_id}", response_model=MessageResponse, summary="删除文档")
async def delete_document(
    doc_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin),
):
    """删除文档及其关联的暂存批次"""
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")

    # 查找关联的导入批次并删除暂存记录
    if doc.filename:
        batches = db.query(ImportBatch).filter(ImportBatch.source_file == doc.filename).all()
        for b in batches:
            db.query(ImportStaging).filter(ImportStaging.batch_id == b.batch_id).delete()
            db.delete(b)

    # 删除文件
    if doc.file_path and os.path.isfile(doc.file_path):
        try:
            os.unlink(doc.file_path)
        except OSError:
            pass

    db.delete(doc)
    db.commit()
    return MessageResponse(message=f"已删除文档 {doc.filename}", success=True)


@router.get("/", response_model=List[DocumentResponse], summary="文档列表")
async def get_documents(
    response: Response,
    skip: int = Query(0, ge=0, description="跳过条数"),
    limit: int = Query(100, ge=1, le=500, description="每页条数"),
    db: Session = Depends(get_db)
):
    """获取已上传文档列表"""
    return paginate(db.query(Document), skip, limit, response)


@router.post("/{doc_id}/retry", response_model=MessageResponse, summary="重试解析失败文档")
async def retry_document(
    doc_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin),
    _rl: None = Depends(limit_upload),
):
    """仅重试失败记录；保留原文件，不重新上传，也不会删除既有条文。"""
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    if doc.status != "failed":
        raise HTTPException(status_code=409, detail="只有解析失败的文档可以重试")
    if not doc.file_path or not os.path.isfile(doc.file_path):
        raise HTTPException(status_code=404, detail="原始文件不存在，无法重试")

    doc.status = "pending"
    doc.error_message = None
    doc.processed_at = None
    db.commit()
    background_tasks.add_task(process_document, doc.id, doc.file_path)
    return MessageResponse(message=f"已开始重试解析：{doc.filename}", success=True)


@router.get("/{doc_id}", response_model=DocumentResponse, summary="文档详情")
async def get_document(
    doc_id: int,
    db: Session = Depends(get_db)
):
    """获取单个文档信息"""
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    return doc
