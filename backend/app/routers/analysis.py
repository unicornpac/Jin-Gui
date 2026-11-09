"""
AI分析路由
"""
from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session
from typing import List
from ..database import get_db
from ..pagination import paginate
from ..dependencies import verify_admin, limit_analysis
from ..models import ClassicText, MedicalCase, LearningHistory
from ..schemas import AnalysisQuery, AnalysisResponse, MedicalCaseResponse
from ..services.ai_service import clean_analysis_output, get_ai_service
from ..services.matcher import get_matcher

router = APIRouter()


# 说明：AI 相关配置在应用启动时由 backend/.env 统一加载一次（override=False，环境变量优先）。
# 各端点一律直接读取 os.environ，不再在请求期解析 .env —— 否则会把密钥写回进程环境，
# 既破坏"环境变量优先"的约定，也让测试无法通过置空环境变量来隔离外部调用。


@router.get("/models", summary="当前密钥可用模型列表")
def get_available_models(_admin: str = Depends(verify_admin)):
    """调用提供商 /v1/models 接口，返回当前密钥可用的模型列表（需管理员认证）。

    配置统一在应用启动时由 `.env` 加载一次（`override=False`，环境变量优先），
    这里不再运行期读取 `.env`，避免把密钥重新写回 `os.environ` 造成全局污染。
    """
    import os

    base_url = (os.getenv("OPENAI_BASE_URL") or "").strip().rstrip("/")
    api_key = (os.getenv("OPENAI_API_KEY") or os.getenv("DASHSCOPE_API_KEY") or "").strip()
    if not base_url or not api_key:
        return {"models": [], "error": "未配置 OPENAI_BASE_URL 或 OPENAI_API_KEY"}
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url=base_url)
        resp = client.models.list()
        models = [{"id": m.id} for m in resp.data]
        return {"models": models, "provider": base_url}
    except Exception as e:
        return {"models": [], "error": str(e), "provider": base_url}


@router.get("/status", summary="AI 配置状态")
async def get_ai_status(_admin: str = Depends(verify_admin)):
    """检查 AI API 是否已配置（需管理员认证；含 provider 名称，故不对公网开放）。"""
    import os

    base_url = os.getenv("OPENAI_BASE_URL", "")
    has_key = bool(os.getenv("OPENAI_API_KEY") or os.getenv("DASHSCOPE_API_KEY"))
    debug = {
        "OPENAI_BASE_URL": "已设置" if base_url else "未设置",
        "OPENAI_API_KEY": "已设置" if os.getenv("OPENAI_API_KEY") else "未设置",
        "AI_MODEL": os.getenv("AI_MODEL", "(默认)"),
    }
    if base_url and has_key:
        if "maas.example.edu.cn" in base_url:
            provider = "自建 MaaS (maas.example.edu.cn)"
        elif "linvk" in base_url:
            provider = "Linvk (ai.linvk.com)"
        else:
            provider = f"自定义 ({base_url[:30]}...)"
        return {"configured": True, "provider": provider, "debug": debug}
    if os.getenv("DASHSCOPE_API_KEY"):
        key = os.getenv("DASHSCOPE_API_KEY", "")
        provider = "OpenAI (GPT)" if key.startswith("sk-proj-") else "通义千问"
        return {"configured": True, "provider": provider, "debug": debug}
    if os.getenv("OPENAI_API_KEY"):
        return {"configured": True, "provider": "OpenAI (GPT)", "debug": debug}
    if os.getenv("BAIDU_API_KEY") and os.getenv("BAIDU_SECRET_KEY"):
        return {"configured": True, "provider": "文心一言", "debug": debug}
    return {"configured": False, "provider": None, "debug": debug}


@router.post("/query", response_model=AnalysisResponse, summary="条文分析")
def analyze_text(
    query: AnalysisQuery,
    db: Session = Depends(get_db),
    _rl: None = Depends(limit_analysis),
):
    """输入条文内容，匹配相关病案并返回AI分析结果"""
    # 1. 在数据库中搜索匹配的条文
    matched_text = db.query(ClassicText).filter(
        ClassicText.content.contains(query.text)
    ).first()
    
    text_id = matched_text.id if matched_text else None
    text_content = matched_text.content if matched_text else query.text
    
    # 2. 使用智能匹配算法查找相关病案
    matcher = get_matcher()
    
    # 如果有匹配的条文，使用智能匹配
    if matched_text:
        scored_cases = matcher.find_related_cases(matched_text, db, limit=5)
        matched_cases = [case for case, score in scored_cases]
    else:
        # 如果没有匹配的条文，使用关键词匹配（symptoms 可能为 NULL）
        from sqlalchemy import or_
        matched_cases = db.query(MedicalCase).filter(
            or_(
                MedicalCase.content.contains(query.text),
                MedicalCase.symptoms.isnot(None) & MedicalCase.symptoms.contains(query.text)
            )
        ).limit(5).all()
    
    # 3. 使用 AI 进行深度分析（配置已在应用启动时统一加载，此处不再读 .env）
    ai_service = get_ai_service()
    model_override = getattr(query, "model", None) if hasattr(query, "model") else None

    if matched_cases:
        # 有病案：分析条文与病案关联
        primary_case = matched_cases[0]
        ai_result = ai_service.analyze_text_case_relation(text_content, primary_case.content, model_override)
        analysis_result = ai_result.get("analysis", "")
        if len(matched_cases) > 1:
            analysis_result += f"\n\n【其他相关病案】\n共找到 {len(matched_cases)} 个相关病案，已对第一个进行详细分析。"
    else:
        # 无病案：仅对条文进行AI解读分析
        ai_result = ai_service.analyze_text_only(text_content, model_override)
        analysis_result = ai_result.get("analysis", "")
        if len(analysis_result) < 100:
            analysis_result += "\n\n【提示】未在数据库中找到相关病案。建议添加病案后再次分析，可获得条文与病案的关联解读。"

    # 所有提供方和追加说明都通过同一纯文本处理，供条文学习页直接展示。
    analysis_result = clean_analysis_output(analysis_result)
    
    # 4. 保存学习记录
    history = LearningHistory(
        user_query=query.text,
        text_id=text_id,
        case_id=matched_cases[0].id if matched_cases else None,
        analysis_result=analysis_result
    )
    db.add(history)
    db.commit()
    
    return AnalysisResponse(
        text_id=text_id,
        text_content=text_content,
        matched_cases=[MedicalCaseResponse.model_validate(case) for case in matched_cases],
        analysis_result=analysis_result
    )


@router.get("/history", summary="分析历史")
async def get_analysis_history(
    response: Response,
    skip: int = Query(0, ge=0, description="跳过条数"),
    limit: int = Query(20, ge=1, le=100, description="每页条数"),
    db: Session = Depends(get_db)
):
    """获取学习分析历史记录（含 id 供删除使用）"""
    rows = paginate(db.query(LearningHistory).order_by(LearningHistory.id.desc()), skip, limit, response)
    return [
        {
            "id": r.id,
            "user_query": r.user_query,
            "query_time": r.query_time.isoformat() if r.query_time else None,
            "analysis_result": r.analysis_result,
        }
        for r in rows
    ]


@router.delete("/log/{log_id}", status_code=204, summary="删除一条日志")
async def delete_analysis_log(log_id: int, db: Session = Depends(get_db), _admin: str = Depends(verify_admin)):
    """删除指定 ID 的学习记录"""
    from fastapi import HTTPException
    from fastapi.responses import Response
    log = db.query(LearningHistory).filter(LearningHistory.id == log_id).first()
    if not log:
        raise HTTPException(status_code=404, detail="记录不存在")
    db.delete(log)
    db.commit()
    return Response(status_code=204)
