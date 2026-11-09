"""
用户反馈路由 —— 提交反馈（公开）+ 管理反馈（管理端）
"""
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ..database import get_db
from ..pagination import paginate
from ..dependencies import verify_admin
from ..models import Feedback
from ..schemas import FeedbackCreate, FeedbackUpdate, FeedbackResponse, MessageResponse

router = APIRouter()


@router.post("/", response_model=MessageResponse, status_code=201, summary="提交反馈")
async def submit_feedback(
    body: FeedbackCreate,
    db: Session = Depends(get_db),
):
    """公开接口：任何用户可提交反馈"""
    fb = Feedback(
        session_id=body.session_id,
        category=body.category,
        content=body.content,
        contact=body.contact,
        status="pending",
    )
    db.add(fb)
    db.commit()
    return MessageResponse(message="感谢你的反馈！我们会认真处理。", success=True)


@router.get("/", response_model=List[FeedbackResponse], summary="反馈列表")
async def list_feedback(
    response: Response,
    category: Optional[str] = Query(None, description="按类别筛选"),
    status: Optional[str] = Query(None, description="按状态筛选：pending/resolved/closed"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin),
):
    """管理端：获取反馈列表"""
    q = db.query(Feedback)
    if category:
        q = q.filter(Feedback.category == category)
    if status:
        q = q.filter(Feedback.status == status)

    items = paginate(q.order_by(Feedback.created_at.desc()), skip, limit, response)

    result = []
    for fb in items:
        session_difficulty = None
        if fb.session_id and fb.session:
            session_difficulty = fb.session.difficulty_level
        result.append(FeedbackResponse(
            id=fb.id,
            session_id=fb.session_id,
            category=fb.category,
            content=fb.content,
            contact=fb.contact,
            status=fb.status,
            admin_note=fb.admin_note,
            created_at=fb.created_at,
            resolved_at=fb.resolved_at,
            session_difficulty=session_difficulty,
        ))
    return result


@router.put("/{feedback_id}", response_model=MessageResponse, summary="更新反馈状态")
async def update_feedback(
    feedback_id: int,
    body: FeedbackUpdate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin),
):
    """管理端：更新反馈状态或添加备注"""
    fb = db.query(Feedback).filter(Feedback.id == feedback_id).first()
    if not fb:
        raise HTTPException(status_code=404, detail="反馈不存在")

    if body.status is not None:
        fb.status = body.status
        if body.status in ("resolved", "closed"):
            fb.resolved_at = datetime.now()

    if body.admin_note is not None:
        fb.admin_note = body.admin_note

    db.commit()
    return MessageResponse(message="已更新", success=True)


@router.delete("/{feedback_id}", response_model=MessageResponse, summary="删除反馈")
async def delete_feedback(
    feedback_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin),
):
    """管理端：删除反馈"""
    fb = db.query(Feedback).filter(Feedback.id == feedback_id).first()
    if not fb:
        raise HTTPException(status_code=404, detail="反馈不存在")

    db.delete(fb)
    db.commit()
    return MessageResponse(message="已删除", success=True)
