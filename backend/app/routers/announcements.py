"""网站公告路由 —— 学生端只读，管理端增删改。"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import verify_admin
from ..models import Announcement
from ..pagination import paginate
from ..schemas import (
    AnnouncementCreate, AnnouncementUpdate, AnnouncementResponse, MessageResponse,
)

router = APIRouter()


@router.get("/", response_model=List[AnnouncementResponse], summary="公告列表（学生端）")
async def list_announcements(
    response: Response,
    db: Session = Depends(get_db),
    skip: int = 0,
    limit: int = 20,
):
    """只返回启用中的公告，最新的在前。学生端与首页横幅都用这个。"""
    query = db.query(Announcement).filter(Announcement.is_active.is_(True)) \
        .order_by(Announcement.created_at.desc(), Announcement.id.desc())
    return paginate(query, skip, limit, response)


@router.get("/admin/", response_model=List[AnnouncementResponse], summary="公告列表（管理端）")
async def list_announcements_admin(
    response: Response,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin),
    skip: int = 0,
    limit: int = 50,
):
    """管理端看全部，包括已停用的。"""
    query = db.query(Announcement).order_by(
        Announcement.created_at.desc(), Announcement.id.desc())
    return paginate(query, skip, limit, response)


@router.post("/", response_model=AnnouncementResponse, status_code=201, summary="发布公告")
async def create_announcement(
    body: AnnouncementCreate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin),
):
    item = Announcement(
        title=body.title.strip(),
        content=body.content.strip(),
        is_active=body.is_active,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.put("/{announcement_id}", response_model=AnnouncementResponse, summary="修改公告")
async def update_announcement(
    announcement_id: int,
    body: AnnouncementUpdate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin),
):
    item = db.query(Announcement).filter(Announcement.id == announcement_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="公告不存在")
    data = body.model_dump(exclude_unset=True)
    if "title" in data and data["title"] is not None:
        data["title"] = data["title"].strip()
    if "content" in data and data["content"] is not None:
        data["content"] = data["content"].strip()
    for field, value in data.items():
        setattr(item, field, value)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/{announcement_id}", response_model=MessageResponse, summary="删除公告")
async def delete_announcement(
    announcement_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin),
):
    item = db.query(Announcement).filter(Announcement.id == announcement_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="公告不存在")
    db.delete(item)
    db.commit()
    return MessageResponse(message="公告已删除", success=True)
