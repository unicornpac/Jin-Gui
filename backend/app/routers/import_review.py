"""
导入审核路由 —— 暂存区查看、人工确认、一键发布。
"""
import uuid
import json
import hashlib
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import func as sqlfunc

from ..database import get_db
from ..dependencies import verify_admin
from ..models import ImportBatch, ImportStaging, ClassicText

router = APIRouter(prefix="/api/import", tags=["导入管理"])


def generate_batch_id() -> str:
    return uuid.uuid4().hex[:12]


@router.get("/batches", summary="导入批次列表")
async def list_batches(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin),
):
    """列出所有导入批次及其状态"""
    batches = db.query(ImportBatch).order_by(ImportBatch.created_at.desc()).all()
    return [
        {
            "id": b.id,
            "batch_id": b.batch_id,
            "source_file": b.source_file,
            "source_edition": b.source_edition,
            "total_articles": b.total_articles,
            "unique_numbers": b.unique_numbers,
            "status": b.status,
            "created_at": b.created_at.isoformat() if b.created_at else None,
            "published_at": b.published_at.isoformat() if b.published_at else None,
        }
        for b in batches
    ]


@router.get("/batches/{batch_id}", summary="批次详情与质检报告")
async def batch_detail(
    batch_id: str,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin),
):
    """查看某个批次详情，包括质检报告"""
    batch = db.query(ImportBatch).filter(ImportBatch.batch_id == batch_id).first()
    if not batch:
        raise HTTPException(status_code=404, detail="批次不存在")

    # 统计暂存区状态
    staging_stats = db.query(
        ImportStaging.status,
        sqlfunc.count(ImportStaging.id)
    ).filter(ImportStaging.batch_id == batch_id).group_by(ImportStaging.status).all()
    stats = {s: c for s, c in staging_stats}

    quality_report = None
    if batch.quality_report:
        try:
            quality_report = json.loads(batch.quality_report)
        except json.JSONDecodeError:
            quality_report = {"raw": batch.quality_report}

    return {
        "batch_id": batch.batch_id,
        "source_file": batch.source_file,
        "source_hash": batch.source_hash,
        "source_edition": batch.source_edition,
        "total_articles": batch.total_articles,
        "unique_numbers": batch.unique_numbers,
        "status": batch.status,
        "quality_report": quality_report,
        "staging_stats": stats,
        "created_at": batch.created_at.isoformat() if batch.created_at else None,
        "published_at": batch.published_at.isoformat() if batch.published_at else None,
    }


@router.get("/batches/{batch_id}/texts", summary="查看暂存条文")
async def list_staging_texts(
    batch_id: str,
    status: Optional[str] = Query(None, description="筛选状态：needs_review/approved/rejected"),
    skip: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=1000),
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin),
):
    """查看某批次的暂存条文列表"""
    q = db.query(ImportStaging).filter(ImportStaging.batch_id == batch_id)
    if status:
        q = q.filter(ImportStaging.status == status)
    total = q.count()
    items = q.order_by(ImportStaging.article_number, ImportStaging.id).offset(skip).limit(limit).all()

    return {
        "total": total,
        "items": [
            {
                "id": s.id,
                "article_number": s.article_number,
                "chapter": s.chapter,
                "section": s.section,
                "content": s.content,
                "raw_content": s.raw_content,
                "layout_marker": s.layout_marker,
                "source_offset": s.source_offset,
                "status": s.status,
                "issue": s.issue,
                "duplicate_of": s.duplicate_of,
            }
            for s in items
        ],
    }


@router.post("/batches/{batch_id}/approve/{staging_id}", summary="批准单条")
async def approve_single(
    batch_id: str,
    staging_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin),
):
    """批准单条暂存条文"""
    item = db.query(ImportStaging).filter(
        ImportStaging.id == staging_id,
        ImportStaging.batch_id == batch_id,
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="暂存记录不存在")
    item.status = "approved"
    item.issue = None
    db.commit()
    return {"message": f"条号 {item.article_number} 已批准", "success": True}


@router.post("/batches/{batch_id}/reject/{staging_id}", summary="驳回单条")
async def reject_single(
    batch_id: str,
    staging_id: int,
    reason: str = Query("", description="驳回原因"),
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin),
):
    """驳回单条暂存条文"""
    item = db.query(ImportStaging).filter(
        ImportStaging.id == staging_id,
        ImportStaging.batch_id == batch_id,
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="暂存记录不存在")
    item.status = "rejected"
    item.issue = f"人工驳回: {reason}" if reason else "人工驳回"
    db.commit()
    return {"message": f"条号 {item.article_number} 已驳回", "success": True}


@router.post("/batches/{batch_id}/approve-all", summary="批准全部待审核条文")
async def approve_all(
    batch_id: str,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin),
):
    """一键批准批次中所有 needs_review 的条文"""
    updated = db.query(ImportStaging).filter(
        ImportStaging.batch_id == batch_id,
        ImportStaging.status == "needs_review",
    ).update({"status": "approved"}, synchronize_session=False)
    db.commit()
    return {"message": f"已批准 {updated} 条", "count": updated, "success": True}


@router.delete("/batches/{batch_id}/texts/{staging_id}", summary="删除暂存条文")
async def delete_staging(
    batch_id: str,
    staging_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin),
):
    """删除暂存区单条条文"""
    item = db.query(ImportStaging).filter(
        ImportStaging.id == staging_id,
        ImportStaging.batch_id == batch_id,
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="暂存记录不存在")
    num = item.article_number
    db.delete(item)
    db.commit()
    return {"message": f"已删除条号 {num}", "success": True}


@router.post("/batches/{batch_id}/publish", summary="发布到正式条文库")
async def publish_batch(
    batch_id: str,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin),
):
    """
    将批次中已批准的条文发布到 classic_texts。

    只有被明确批准（status=approved）的条文才会被写入正式库。
    被驳回（rejected）或待审核（needs_review）的条文不会发布。
    """
    batch = db.query(ImportBatch).filter(ImportBatch.batch_id == batch_id).first()
    if not batch:
        raise HTTPException(status_code=404, detail="批次不存在")
    if batch.status == "published":
        raise HTTPException(status_code=409, detail="该批次已发布，不能重复发布")

    # 获取已批准的条文
    approved = db.query(ImportStaging).filter(
        ImportStaging.batch_id == batch_id,
        ImportStaging.status == "approved",
    ).order_by(ImportStaging.article_number).all()

    if not approved:
        raise HTTPException(status_code=400, detail="没有已批准的条文可以发布")

    # 写入 classic_texts
    published_count = 0
    skipped_count = 0
    for item in approved:
        # 去重：相同 条号+来源书+篇章 不重复添加
        existing = db.query(ClassicText).filter(
            ClassicText.article_number == item.article_number,
            ClassicText.source_book == item.source_book,
            ClassicText.chapter == item.chapter,
        ).first()
        if existing:
            # 更新已有记录
            existing.content = item.content
            existing.raw_content = item.raw_content
            existing.layout_marker = item.layout_marker
            existing.chapter = item.chapter
            existing.section = item.section
            existing.source_file = item.source_file
            existing.source_hash = item.source_hash
            existing.source_offset = item.source_offset
            existing.source_edition = item.source_edition
            existing.import_batch_id = batch_id
            existing.updated_at = datetime.now()
            skipped_count += 1
        else:
            text = ClassicText(
                source_book=item.source_book,
                chapter=item.chapter,
                section=item.section,
                article_number=item.article_number,
                order_index=item.article_number,
                content=item.content,
                raw_content=item.raw_content,
                layout_marker=item.layout_marker,
                source_file=item.source_file,
                source_hash=item.source_hash,
                source_offset=item.source_offset,
                source_edition=item.source_edition,
                import_batch_id=batch_id,
                keywords=item.keywords or "",
            )
            db.add(text)
            published_count += 1

    batch.status = "published"
    batch.published_at = datetime.now()
    db.commit()

    return {
        "message": f"发布完成：新增 {published_count} 条，更新 {skipped_count} 条",
        "new": published_count,
        "updated": skipped_count,
        "success": True,
    }


@router.post("/batches/{batch_id}/reject-batch", summary="驳回整个批次")
async def reject_batch(
    batch_id: str,
    reason: str = Query("", description="驳回原因"),
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin),
):
    """驳回整个批次"""
    batch = db.query(ImportBatch).filter(ImportBatch.batch_id == batch_id).first()
    if not batch:
        raise HTTPException(status_code=404, detail="批次不存在")
    batch.status = "rejected"
    # 所有暂存记录标记为驳回
    db.query(ImportStaging).filter(ImportStaging.batch_id == batch_id).update(
        {"status": "rejected", "issue": f"批次驳回: {reason}" if reason else "批次驳回"},
        synchronize_session=False,
    )
    db.commit()
    return {"message": "批次已驳回", "success": True}


@router.put("/batches/{batch_id}/edit/{staging_id}", summary="编辑暂存条文")
async def edit_staging(
    batch_id: str,
    staging_id: int,
    content: str = Query(None, description="规范正文"),
    raw_content: str = Query(None, description="原始文本"),
    article_number: int = Query(None, description="条号"),
    chapter: str = Query(None, description="篇章名"),
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin),
):
    """编辑暂存区单条条文的内容、条号或章节"""
    item = db.query(ImportStaging).filter(
        ImportStaging.id == staging_id,
        ImportStaging.batch_id == batch_id,
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="暂存记录不存在")

    changed = []
    if content is not None:
        item.content = content
        changed.append("正文")
    if raw_content is not None:
        item.raw_content = raw_content
        changed.append("原始文本")
    if article_number is not None:
        item.article_number = article_number
        changed.append("条号")
    if chapter is not None:
        item.chapter = chapter
        changed.append("章节")

    db.commit()
    return {"message": f"已更新{'、'.join(changed)}", "success": True}


@router.post("/batches/{batch_id}/texts", summary="新增暂存条文")
async def create_staging(
    batch_id: str,
    article_number: int = Query(..., description="条号"),
    content: str = Query(..., description="规范正文"),
    chapter: str = Query(None, description="篇章名"),
    raw_content: str = Query(None, description="原始文本"),
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin),
):
    """在暂存区手动新增一条条文（用于补充解析遗漏的条文）"""
    batch = db.query(ImportBatch).filter(ImportBatch.batch_id == batch_id).first()
    if not batch:
        raise HTTPException(status_code=404, detail="批次不存在")

    book = "《金匮要略》"
    if batch.source_file and "伤寒" in batch.source_file:
        book = "《伤寒论》"

    stg = ImportStaging(
        batch_id=batch_id,
        source_book=book,
        chapter=chapter,
        article_number=article_number,
        order_index=article_number,
        raw_content=raw_content or content,
        content=content,
        source_file=batch.source_file,
        source_hash=batch.source_hash,
        status="needs_review",
    )
    db.add(stg)
    db.commit()
    db.refresh(stg)
    return {"message": f"已新增条号 {article_number}", "id": stg.id, "success": True}
