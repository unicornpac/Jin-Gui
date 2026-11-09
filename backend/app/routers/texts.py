"""
条文管理路由 —— 支持书→篇章→条文三层结构 + 互联网校验
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session
from typing import List, Optional
from ..database import get_db
from ..pagination import paginate
from ..dependencies import verify_admin
from ..models import ClassicText, ChapterMeta
from ..schemas import (
    ClassicTextCreate, ClassicTextUpdate, ClassicTextResponse,
    BatchDeleteIds, MessageResponse, TextVerifyRequest, TextVerifyResponse,
    TextVerifyBatchResponse
)

router = APIRouter()


@router.post("/", response_model=ClassicTextResponse, status_code=201, summary="创建条文")
async def create_text(
    text: ClassicTextCreate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin),
):
    """创建新条文"""
    db_text = ClassicText(**text.model_dump())
    db.add(db_text)
    db.commit()
    db.refresh(db_text)
    return db_text


@router.get("/", response_model=List[ClassicTextResponse], summary="条文列表")
async def get_texts(
    response: Response,
    skip: int = Query(0, ge=0, description="跳过条数"),
    limit: int = Query(100, ge=1, le=3000, description="每页条数"),
    source_book: Optional[str] = Query(None, description="来源经典筛选"),
    chapter: Optional[str] = Query(None, description="篇章筛选"),
    section: Optional[str] = Query(None, description="子篇筛选（上/中/下）"),
    keyword: Optional[str] = Query(None, description="关键词搜索"),
    verified: Optional[bool] = Query(None, description="校验状态筛选"),
    sort_by: Optional[str] = Query("article_number", description="排序字段"),
    sort_order: Optional[str] = Query("asc", description="排序方向：asc/desc"),
    db: Session = Depends(get_db)
):
    """获取条文列表，支持按经典来源、篇章、关键词、校验状态筛选"""
    query = db.query(ClassicText)
    
    if source_book:
        query = query.filter(ClassicText.source_book.contains(source_book))
    if chapter:
        query = query.filter(ClassicText.chapter.contains(chapter))
    if section:
        query = query.filter(ClassicText.section == section)
    if keyword:
        query = query.filter(
            ClassicText.content.contains(keyword) |
            ClassicText.keywords.contains(keyword)
        )
    if verified is not None:
        query = query.filter(ClassicText.verified == verified)
    
    # 排序：优先按 article_number，其次按 order_index
    # 分页与排序需要同时生效，因此排序交给后端：字段由 sort_by 指定，方向由 sort_order 指定
    sort_column = {
        "article_number": ClassicText.article_number,
        "order_index": ClassicText.order_index,
        "id": ClassicText.id,
        "source_book": ClassicText.source_book,
        "chapter": ClassicText.chapter,
    }.get(sort_by, ClassicText.article_number)
    ordered = sort_column.desc() if sort_order == "desc" else sort_column.asc()
    query = query.order_by(ordered.nullslast())
    
    return paginate(query, skip, limit, response)


@router.get("/chapters", summary="篇章树")
async def get_chapter_tree(
    source_book: Optional[str] = Query(None, description="按书筛选"),
    db: Session = Depends(get_db)
):
    """
    获取条文篇章树结构（用于前端层级展��）
    返回：书 → 篇章 → 子篇 → 条文数
    """
    from sqlalchemy import func as sqlfunc
    
    # 从 chapter_meta 获取标准结构
    meta_query = db.query(ChapterMeta)
    if source_book:
        meta_query = meta_query.filter(ChapterMeta.book.contains(source_book))
    chapters = meta_query.order_by(ChapterMeta.order_index).all()
    
    # 统计每个篇章的实际条文数
    counts = {}
    rows = db.query(
        ClassicText.source_book, ClassicText.chapter, ClassicText.section,
        sqlfunc.count(ClassicText.id)
    ).group_by(ClassicText.source_book, ClassicText.chapter, ClassicText.section).all()
    for book, ch, sec, cnt in rows:
        key = f"{book}|{ch}|{sec or ''}"
        counts[key] = cnt
    
    # 构建树
    tree = {}
    for meta in chapters:
        book = meta.book
        if book not in tree:
            tree[book] = {"book": book, "chapters": []}
        key = f"{book}|{meta.chapter}|{meta.section or ''}"
        tree[book]["chapters"].append({
            "chapter": meta.chapter,
            "section": meta.section,
            "order": meta.order_index,
            "expected_count": meta.article_count_expected,
            "actual_count": counts.get(key, 0),
        })
    
    return list(tree.values())


@router.get("/distribution", summary="条文分布校验")
async def get_distribution(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin),
):
    """
    统计条文在各篇章中的分布，用于验收分层是否正确
    """
    from sqlalchemy import func as sqlfunc
    
    rows = db.query(
        ClassicText.source_book, ClassicText.chapter,
        sqlfunc.count(ClassicText.id)
    ).group_by(ClassicText.source_book, ClassicText.chapter).order_by(
        ClassicText.source_book, ClassicText.chapter
    ).all()
    
    total = 0
    distribution = []
    for book, ch, cnt in rows:
        total += cnt
        distribution.append({"book": book, "chapter": ch, "count": cnt})
    
    return {
        "total": total,
        "distribution": distribution,
        "expected_total": 794,
        "books": list(set(r[0] for r in rows)),
    }


@router.post("/batch-delete", response_model=MessageResponse, summary="批量删除条文")
async def batch_delete_texts(
    body: BatchDeleteIds,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin),
):
    """批量删除指定ID的条文"""
    ids = body.ids or []
    if not ids:
        return MessageResponse(message="未指定要删除的ID", success=False)
    deleted = db.query(ClassicText).filter(ClassicText.id.in_(ids)).delete(synchronize_session=False)
    db.commit()
    return MessageResponse(message=f"已删除 {deleted} 条条文", success=True)


@router.get("/{text_id}", response_model=ClassicTextResponse, summary="获取条文")
async def get_text(
    text_id: int,
    db: Session = Depends(get_db)
):
    """获取单个条文"""
    text = db.query(ClassicText).filter(ClassicText.id == text_id).first()
    if not text:
        raise HTTPException(status_code=404, detail="条文不存在")
    return text


@router.put("/{text_id}", response_model=ClassicTextResponse, summary="更新条文")
async def update_text(
    text_id: int,
    text_update: ClassicTextUpdate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin),
):
    """更新条文"""
    text = db.query(ClassicText).filter(ClassicText.id == text_id).first()
    if not text:
        raise HTTPException(status_code=404, detail="条文不存在")
    
    update_data = text_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(text, field, value)
    
    db.commit()
    db.refresh(text)
    return text


@router.delete("/{text_id}", status_code=204, summary="删除条文")
async def delete_text(
    text_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin),
):
    text = db.query(ClassicText).filter(ClassicText.id == text_id).first()
    if not text:
        raise HTTPException(status_code=404, detail="条文不存在")
    
    db.delete(text)
    db.commit()
    return Response(status_code=204)


# ==================== 互联网校验端点 ====================

@router.post("/verify/single", response_model=TextVerifyResponse, summary="单条校验")
def verify_single_text(
    req: TextVerifyRequest,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin),
):
    """对单条条文执行互联网比对校验"""
    from ..services.text_verifier import get_verifier
    verifier = get_verifier()
    result = verifier.verify_single(db, req.text_id)
    return result


@router.post("/verify/fix-single", response_model=TextVerifyResponse, summary="校验并修复单条")
def verify_and_fix_single(
    req: TextVerifyRequest,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin),
):
    """校验单条条文，如果分类不对则自动修复"""
    from ..services.text_verifier import get_verifier
    verifier = get_verifier()
    result = verifier.verify_and_fix_single(db, req.text_id)
    return result


@router.post("/verify/batch", response_model=TextVerifyBatchResponse, summary="批量校验")
def verify_batch(
    fix: bool = Query(False, description="是否自动修复分类错误"),
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin),
):
    """批量校验未验证的条文（每次最多50条）"""
    from ..services.text_verifier import get_verifier
    verifier = get_verifier()
    result = verifier.verify_batch(db, fix=fix)
    return result


@router.post("/seed-chapters", response_model=MessageResponse, summary="初始化篇章元数据")
async def seed_chapters(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin),
):
    """将《伤寒论》和《金匮要略》的正确篇章结构写入数据库"""
    from ..services.text_verifier import get_verifier
    verifier = get_verifier()
    count = verifier.seed_chapter_meta(db)
    return MessageResponse(
        message=f"篇章元数据初始化完成，已写入 {count} 条记录" if count > 0 else f"已存在 {count} 条，无需初始化",
        success=True
    )
