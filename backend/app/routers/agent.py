"""
智能体训练路由 —— 三阶梯多轮交互 API

API 端点：
- POST /api/agent/session/start     — 开始新训练会话
- POST /api/agent/session/{id}/message — 发送消息
- GET  /api/agent/session/{id}       — 获取会话详情
- POST /api/agent/session/{id}/evaluate — 结束并评价
- GET  /api/agent/sessions           — 获取会话列表
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session
from typing import List
from ..database import get_db
from ..pagination import paginate
from ..dependencies import (
    verify_admin,
    verify_admin_optional,
    limit_agent_start,
    limit_agent_message,
)
from ..models import TrainingSession, SessionMessage, MedicalCase, ClassicText
from ..schemas import (
    SessionStartRequest, SessionStartResponse,
    SessionMessageRequest, SessionMessageResponse,
    SessionDetailResponse, SessionEvaluateResponse,
    MessageResponse, PublicStatsResponse
)
from ..services.agent_service import get_agent, TrainingAgent
from ..services.session_token import issue_session_token, verify_session_token
from ..services.guidance import build_guidance

router = APIRouter()


def _assert_session_owner(session_id: int, request: Request) -> None:
    """校验请求方持有该会话的归属令牌。

    令牌由 session_id 与 SESSION_SECRET/ADMIN_PASSWORD 经 HMAC 派生，不落库，
    因此没有密钥的一方无法枚举或接管他人会话。
    """
    if not verify_session_token(session_id, request.headers.get("X-Session-Token")):
        raise HTTPException(status_code=403, detail="会话令牌无效或缺失")


@router.get("/public-stats", response_model=PublicStatsResponse, summary="公开聚合统计")
async def get_public_stats(db: Session = Depends(get_db)):
    """首页统计数据；只返回总数和平均分，不暴露训练会话明细。"""
    import re

    score_values = db.query(TrainingSession.score).filter(
        TrainingSession.score.isnot(None)
    ).all()
    numeric_scores = []
    for (score,) in score_values:
        match = re.match(r"^\s*(\d+(?:\.\d+)?)", str(score))
        if match:
            numeric_scores.append(float(match.group(1)))

    average_score = (
        round(sum(numeric_scores) / len(numeric_scores), 1)
        if numeric_scores else None
    )
    return PublicStatsResponse(
        text_count=db.query(ClassicText).count(),
        case_count=db.query(MedicalCase).count(),
        session_count=db.query(TrainingSession).count(),
        average_score=average_score,
    )


@router.post("/session/start", response_model=SessionStartResponse, summary="开始训练")
def start_session(
    req: SessionStartRequest,
    db: Session = Depends(get_db),
    _rl: None = Depends(limit_agent_start),
    agent: TrainingAgent = Depends(get_agent),
):
    """开始一个新的临床思辨训练会话"""
    try:
        session, opening = agent.create_session(
            db=db,
            difficulty_level=req.difficulty_level,
            student_id=req.student_id or "anonymous",
            case_id=req.case_id
        )
        return SessionStartResponse(
            session_id=session.id,
            difficulty_level=session.difficulty_level,
            case_title=session.case.title if session.case else "未知病案",
            agent_message=opening,
            session_token=issue_session_token(session.id),
            guidance=build_guidance(
                session.difficulty_level,
                {"辨病": False, "平脉": False, "析证": False, "定治": False},
                [],
                0,
            ),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"创建会话失败: {str(e)}")


@router.post("/session/{session_id}/message", response_model=SessionMessageResponse, summary="发送消息")
def send_message(
    session_id: int,
    req: SessionMessageRequest,
    request: Request,
    db: Session = Depends(get_db),
    _rl: None = Depends(limit_agent_message),
    agent: TrainingAgent = Depends(get_agent),
):
    """向智能体发送消息，获取回复"""
    _assert_session_owner(session_id, request)
    try:
        agent_response, msg_type, session_status, progress = agent.process_message(
            db=db,
            session_id=session_id,
            student_content=req.content
        )
        return SessionMessageResponse(
            agent_message=agent_response,
            message_type=msg_type,
            session_status=session_status,
            progress=progress
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"消息处理失败: {str(e)}")


@router.get(
    "/session/{session_id}",
    response_model=SessionDetailResponse,
    summary="会话详情（教师端或会话持有者）",
)
async def get_session_detail(
    session_id: int,
    request: Request,
    db: Session = Depends(get_db),
    _admin: bool = Depends(verify_admin_optional),
):
    """获取训练会话详情。

    教师端（管理员认证）可读任意会话；学生凭 `X-Session-Token` 只能读自己的会话，
    这个凭据同时用于刷新页面后恢复训练。
    """
    if not _admin and not verify_session_token(
        session_id, request.headers.get("X-Session-Token")
    ):
        raise HTTPException(status_code=401, detail="需要管理员认证或有效的会话令牌")

    session = db.query(TrainingSession).filter(TrainingSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    
    messages = db.query(SessionMessage).filter(
        SessionMessage.session_id == session_id
    ).order_by(SessionMessage.created_at).all()
    
    return SessionDetailResponse(
        id=session.id,
        student_id=session.student_id,
        difficulty_level=session.difficulty_level,
        status=session.status,
        case_title=session.case.title if session.case else None,
        decision_path=session.decision_path,
        score=session.score,
        started_at=session.started_at,
        ended_at=session.ended_at,
        messages=[
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "message_type": m.message_type,
                "key_decision": m.key_decision,
                "created_at": m.created_at.isoformat() if m.created_at else None
            }
            for m in messages
        ]
    )


@router.post("/session/{session_id}/evaluate", response_model=SessionEvaluateResponse, summary="结束并评价")
def evaluate_session(
    session_id: int,
    request: Request,
    db: Session = Depends(get_db),
    _rl: None = Depends(limit_agent_start),
    agent: TrainingAgent = Depends(get_agent),
):
    """结束训练会话并生成 AI 评价报告（含病案揭晓）。

    响应包含 `case_correct_answer`，因此必须先通过会话归属令牌校验，
    否则枚举自增 id 即可批量获取全部病案答案。
    """
    _assert_session_owner(session_id, request)
    session = db.query(TrainingSession).filter(TrainingSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    
    case = session.case
    
    # 自动到达轮次上限的会话会先标记 completed，但尚未生成评价，仍应允许首次评价。
    if session.status == "completed" and session.score is not None:
        from ..services.treatment_safety import assess_treatment_safety
        messages = [
            {
                "role": "user" if message.role == "student" else "assistant",
                "content": message.content,
            }
            for message in session.messages
        ]
        return SessionEvaluateResponse(
            session_id=session.id,
            score=session.score or "未评分",
            # 评价报告此前没有落库，重复打开时会拿 decision_path 顶替；
            # 旧数据没有 evaluation 字段，仍回退到 decision_path 保持可读
            evaluation=session.evaluation or session.decision_path or "",
            decision_path=session.decision_path or "",
            case_title=case.title if case else None,
            case_correct_answer=case.correct_answer if case else None,
            related_texts=[],
            safety_feedback=assess_treatment_safety(
                messages, case.prescription if case else None
            ),
            scoring=session.scoring,
        )
    
    try:
        result = agent.evaluate_session(db=db, session_id=session_id)
        return SessionEvaluateResponse(
            session_id=session.id,
            score=result["score"],
            evaluation=result["evaluation"],
            decision_path=result["decision_path"],
            case_title=case.title if case else None,
            case_correct_answer=case.correct_answer if case else None,
            related_texts=result.get("related_texts", []),
            safety_feedback=result.get("safety_feedback"),
            scoring=result.get("scoring"),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"评价生成失败: {str(e)}")


@router.get("/session-summary", summary="训练记录汇总（教师端）")
async def session_summary(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin),
):
    """一次性返回训练记录的总数、进行中、已完成与平均分。

    分页之后前端只能拿到一页数据，无法再自行推算这四个数字，故由后端聚合。
    """
    import re

    total = db.query(TrainingSession).count()
    active = db.query(TrainingSession).filter(TrainingSession.status == "active").count()
    completed = db.query(TrainingSession).filter(TrainingSession.status == "completed").count()

    numeric = []
    for (raw,) in db.query(TrainingSession.score).filter(
        TrainingSession.score.isnot(None)
    ).all():
        match = re.match(r"^\s*(\d+(?:\.\d+)?)", str(raw))
        if match:
            numeric.append(float(match.group(1)))

    return {
        "total": total,
        "active": active,
        "completed": completed,
        "average_score": round(sum(numeric) / len(numeric), 1) if numeric else None,
    }


@router.get("/sessions", summary="会话列表")
async def list_sessions(
    response: Response,
    student_id: str = Query(None, description="按学生筛选"),
    difficulty_level: str = Query(None, description="按难度筛选"),
    status: str = Query(None, description="按状态筛选：active/completed/abandoned"),
    skip: int = Query(0, ge=0, description="跳过条数"),
    limit: int = Query(50, ge=1, le=200, description="每页条数"),
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin),
):
    """获取训练会话列表（教师端可用）"""
    query = db.query(TrainingSession)
    
    if student_id:
        query = query.filter(TrainingSession.student_id == student_id)
    if difficulty_level:
        query = query.filter(TrainingSession.difficulty_level == difficulty_level)
    if status:
        query = query.filter(TrainingSession.status == status)
    
    sessions = paginate(query.order_by(TrainingSession.id.desc()), skip, limit, response)
    
    return [
        {
            "id": s.id,
            "student_id": s.student_id,
            "difficulty_level": s.difficulty_level,
            "status": s.status,
            "case_title": s.case.title if s.case else None,
            "score": s.score,
            "message_count": len(s.messages) if s.messages else 0,
            "started_at": s.started_at.isoformat() if s.started_at else None,
            "ended_at": s.ended_at.isoformat() if s.ended_at else None,
        }
        for s in sessions
    ]


@router.delete("/session/{session_id}", status_code=204, summary="删除会话")
async def delete_session(
    session_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin),
):
    """删除指定训练会话及其所有消息"""
    session = db.query(TrainingSession).filter(TrainingSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    
    # 删除关联消息
    db.query(SessionMessage).filter(SessionMessage.session_id == session_id).delete()
    db.delete(session)
    db.commit()
    
    from fastapi.responses import Response
    return Response(status_code=204)
