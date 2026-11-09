"""
病案管理路由
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session
from typing import List, Optional
from ..database import get_db
from ..pagination import paginate
from ..dependencies import verify_admin
from ..models import MedicalCase
from ..schemas import (
    MedicalCaseCreate, MedicalCaseUpdate, MedicalCaseResponse,
    MedicalCasePublicResponse, BatchDeleteIds, MessageResponse,
)

router = APIRouter()


@router.post("/", response_model=MedicalCaseResponse, status_code=201, summary="创建病案")
async def create_case(
    case: MedicalCaseCreate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin),
):
    """创建新病案"""
    db_case = MedicalCase(**case.model_dump())
    db.add(db_case)
    db.commit()
    db.refresh(db_case)
    return db_case


@router.get("/", response_model=List[MedicalCasePublicResponse], summary="病案列表（公开视图）")
async def get_cases(
    response: Response,
    skip: int = Query(0, ge=0, description="跳过条数"),
    limit: int = Query(100, ge=1, le=1000, description="每页条数"),
    title: Optional[str] = Query(None, description="标题搜索"),
    difficulty_level: Optional[str] = Query(None, description="难度筛选"),
    diagnosis: Optional[str] = Query(None, description="诊断搜索"),
    db: Session = Depends(get_db)
):
    """获取病案列表（学生端视图）。

    只返回标题、内容、症状与难度；诊断、方剂、教学要点、参考答案一律不下发，
    避免未认证调用者直接取得训练标准答案。
    """
    query = db.query(MedicalCase)
    
    if title:
        query = query.filter(MedicalCase.title.contains(title))
    
    if diagnosis:
        query = query.filter(MedicalCase.diagnosis.contains(diagnosis))

    if difficulty_level:
        query = query.filter(MedicalCase.difficulty_level == difficulty_level)
    
    return paginate(query, skip, limit, response)


@router.get("/admin/", response_model=List[MedicalCaseResponse], summary="病案列表（管理端）")
async def get_cases_admin(
    response: Response,
    skip: int = Query(0, ge=0, description="跳过条数"),
    limit: int = Query(100, ge=1, le=1000, description="每页条数"),
    title: Optional[str] = Query(None, description="标题搜索"),
    difficulty_level: Optional[str] = Query(None, description="难度筛选"),
    diagnosis: Optional[str] = Query(None, description="诊断搜索"),
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin),
):
    """管理端病案列表：含诊断、方剂、教学要点与参考答案，需管理员认证。"""
    query = db.query(MedicalCase)

    if title:
        query = query.filter(MedicalCase.title.contains(title))

    if diagnosis:
        query = query.filter(MedicalCase.diagnosis.contains(diagnosis))

    if difficulty_level:
        query = query.filter(MedicalCase.difficulty_level == difficulty_level)

    return paginate(query, skip, limit, response)


@router.get("/admin/{case_id}", response_model=MedicalCaseResponse, summary="病案详情（管理端）")
async def get_case_admin(
    case_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin),
):
    """管理端病案详情：含完整答案字段，需管理员认证。"""
    case = db.query(MedicalCase).filter(MedicalCase.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="病案不存在")
    return case


@router.post("/batch-delete", response_model=MessageResponse, summary="批量删除病案")
async def batch_delete_cases(
    body: BatchDeleteIds,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin),
):
    """批量删除指定ID的病案"""
    ids = body.ids or []
    if not ids:
        return MessageResponse(message="未指定要删除的ID", success=False)
    deleted = db.query(MedicalCase).filter(MedicalCase.id.in_(ids)).delete(synchronize_session=False)
    db.commit()
    return MessageResponse(message=f"已删除 {deleted} 个病案", success=True)


@router.get("/{case_id}", response_model=MedicalCasePublicResponse, summary="病案详情（公开视图）")
async def get_case(
    case_id: int,
    db: Session = Depends(get_db)
):
    """获取单个病案（学生端视图），不含诊断/方剂/教学要点/参考答案。"""
    case = db.query(MedicalCase).filter(MedicalCase.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="病案不存在")
    return case


@router.put("/{case_id}", response_model=MedicalCaseResponse, summary="更新病案")
async def update_case(
    case_id: int,
    case_update: MedicalCaseUpdate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin),
):
    """更新病案"""
    case = db.query(MedicalCase).filter(MedicalCase.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="病案不存在")
    
    update_data = case_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(case, field, value)
    
    db.commit()
    db.refresh(case)
    return case


@router.delete("/{case_id}", status_code=204, summary="删除病案")
async def delete_case(
    case_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin),
):
    """删除病案"""
    case = db.query(MedicalCase).filter(MedicalCase.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="病案不存在")
    
    db.delete(case)
    db.commit()
    return Response(status_code=204)
