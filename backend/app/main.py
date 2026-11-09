"""
FastAPI主应用
"""
from pathlib import Path
from urllib.parse import urlencode
from dotenv import load_dotenv

# logger 必须在最早初始化，因为模块级 .env 加载代码会用到
from .logger import get_logger, set_request_id
logger = get_logger(__name__)

# 启动前加载 .env（仅在环境变量未设置时生效，兼容生产环境）
_BACKEND_DIR = Path(__file__).resolve().parent.parent
_env_file = _BACKEND_DIR / ".env"
if _env_file.exists():
    load_dotenv(_env_file, override=False)  # override=False: 环境变量优先
    logger.info(".env 已加载: %s", _env_file)

import os

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from .database import init_db
from .dependencies import verify_admin_page
from .routers import texts, cases, analysis, documents, agent, import_review, feedback

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
UI_VERSION = "20260804-2"

# 生产环境可设 DISABLE_DOCS=1 关闭交互式文档（/docs、/redoc、/openapi.json）
_DOCS_ENABLED = os.getenv("DISABLE_DOCS", "").strip().lower() not in {"1", "true", "yes"}

# CORS 默认不放行任何跨域来源：本系统前后端同源部署，无需跨域。
# 确有前后端分离部署时，用 CORS_ORIGINS 以逗号分隔显式列出允许的来源。
_CORS_ORIGINS = [
    origin.strip()
    for origin in (os.getenv("CORS_ORIGINS") or "").split(",")
    if origin.strip()
]

# 创建FastAPI应用
app = FastAPI(
    title="金匮要略临床思辨训练系统",
    description="帮助中医学学生增强经典条文与实际病案之间的联系",
    version="1.1.0",
    docs_url="/docs" if _DOCS_ENABLED else None,
    redoc_url="/redoc" if _DOCS_ENABLED else None,
    openapi_url="/openapi.json" if _DOCS_ENABLED else None,
    openapi_tags=[
        {"name": "条文管理", "description": "经典条文的增删改查"},
        {"name": "病案管理", "description": "病案的增删改查"},
        {"name": "AI分析", "description": "条文与病案关联分析"},
        {"name": "文档管理", "description": "上传文档并自动解析"},
        {"name": "智能体训练", "description": "三阶梯临床思辨多轮交互训练"},
        {"name": "运维", "description": "存活与就绪探针"},
    ],
)

# 仅当显式配置了来源时才启用凭据跨域，避免"任意来源 + 携带凭据"的组合
app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=bool(_CORS_ORIGINS),
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=[
        "Authorization", "Content-Type", "X-Request-ID",
        "X-Session-Token", "X-Upload-Password",
    ],
    # 分页计数头需要显式暴露，浏览器端 JS 才能读取（跨域部署时必需）
    expose_headers=["X-Total-Count", "X-Skip", "X-Limit"],
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    """为每个请求注入 X-Request-ID，贯穿日志和响应头"""
    rid = request.headers.get("X-Request-ID", "") or os.urandom(8).hex()
    set_request_id(rid)
    response = await call_next(request)
    response.headers["X-Request-ID"] = rid
    return response


# 全局异常处理：确保 500 等错误返回 JSON
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    from fastapi.responses import JSONResponse

    # FastAPI 内置异常 -> 保留原始状态码（避免 422/401/404 等被吞成 500）
    if isinstance(exc, RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={"detail": exc.errors(), "type": type(exc).__name__}
        )
    if isinstance(exc, HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail, "type": type(exc).__name__}
        )

    # 真正的未预期异常 -> 500
    logger.exception("未预期的异常")
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc), "type": type(exc).__name__}
    )

# 注册路由
app.include_router(texts.router, prefix="/api/texts", tags=["条文管理"])
app.include_router(cases.router, prefix="/api/cases", tags=["病案管理"])
app.include_router(analysis.router, prefix="/api/analysis", tags=["AI分析"])
app.include_router(documents.router, prefix="/api/documents", tags=["文档管理"])
app.include_router(agent.router, prefix="/api/agent", tags=["智能体训练"])
app.include_router(import_review.router)
app.include_router(feedback.router, prefix="/api/feedback", tags=["用户反馈"])
@app.get("/live", tags=["运维"], summary="存活探针")
async def live_check():
    """进程存活探针：只要进程能响应就返回 200，供负载均衡与进程守护使用。"""
    return {"status": "ok"}


@app.get("/ready", tags=["运维"], summary="就绪探针")
async def ready_check():
    """就绪探针：数据库可用返回 200，否则 503。AI 未配置只降级不阻塞。"""
    from fastapi.responses import JSONResponse
    import httpx

    status = "ok"
    db_status = "connected"
    ai_status = "unknown"

    # 1. 检查数据库连接
    try:
        from .database import SessionLocal
        from sqlalchemy import text
        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
        finally:
            db.close()
    except Exception as e:
        db_status = f"error: {e}"
        status = "degraded"

    # 2. 检查 AI API 连通性（非阻塞，失败不影响就绪判定）
    try:
        base_url = (os.getenv("OPENAI_BASE_URL", "") or "").strip().rstrip("/")
        if base_url:
            # trust_env=False：不读系统代理，否则内网端点会被 Clash 之类工具劫持
            async with httpx.AsyncClient(timeout=5.0, trust_env=False) as client:
                resp = await client.get(f"{base_url}/models")
                ai_status = "ready" if resp.status_code < 500 else f"api_error({resp.status_code})"
        else:
            ai_status = "not_configured"
    except Exception as e:
        ai_status = f"unreachable: {str(e)[:80]}"

    http_status = 200 if status == "ok" else 503
    return JSONResponse(
        status_code=http_status,
        content={"status": status, "db": db_status, "ai": ai_status},
    )


@app.get("/health", tags=["运维"], summary="健康检查（兼容 /ready）")
async def health_check():
    """向后兼容端点：行为等同 /ready，保留给既有部署脚本与监控。"""
    return await ready_check()


@app.on_event("startup")
async def startup_event():
    """应用启动时初始化数据库"""
    init_db()
    logger.info("数据库初始化完成")


@app.get("/")
async def root(_: str = Depends(verify_admin_page)):
    """根路径（管理端，需密码）"""
    from fastapi.responses import FileResponse
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path, headers={"Cache-Control": "no-store, max-age=0"})
    return {"message": "金匮要略临床思辨训练系统", "api文档": "/docs"}


@app.get("/user")
async def user_portal():
    """首访用户入口页面。"""
    from fastapi.responses import FileResponse
    user_path = STATIC_DIR / "newcase.html"
    if user_path.exists():
        return FileResponse(user_path, headers={"Cache-Control": "no-store, max-age=0"})
    return {"message": "用户端页面不存在", "hint": "请检查 static/newcase.html"}


@app.get("/portal")
async def returning_user_portal():
    """保留给回访用户的功能门户。"""
    from fastapi.responses import FileResponse
    portal_path = STATIC_DIR / "user.html"
    if portal_path.exists():
        return FileResponse(portal_path, headers={"Cache-Control": "no-store, max-age=0"})
    return {"message": "用户门户不存在", "hint": "请检查 static/user.html"}


@app.get("/newcase")
async def newcase_page():
    """New homepage concept preview."""
    from fastapi.responses import FileResponse
    newcase_path = STATIC_DIR / "newcase.html"
    if newcase_path.exists():
        return FileResponse(newcase_path, headers={"Cache-Control": "no-store, max-age=0"})
    return {"message": "Newcase page not found", "hint": "Check static/newcase.html"}


@app.get("/static/jingui-theme.css", include_in_schema=False)
async def jingui_theme_css():
    """Shared visual theme for the local interface previews."""
    from fastapi.responses import FileResponse
    theme_path = STATIC_DIR / "jingui-theme.css"
    if theme_path.exists():
        return FileResponse(theme_path, media_type="text/css", headers={"Cache-Control": "no-store, max-age=0"})
    raise HTTPException(status_code=404, detail="Theme stylesheet not found")


@app.get("/static/jingui-motion.js", include_in_schema=False)
async def jingui_motion_js():
    """共享的实验性交互渲染层。"""
    from fastapi.responses import FileResponse
    motion_path = STATIC_DIR / "jingui-motion.js"
    if motion_path.exists():
        return FileResponse(motion_path, media_type="application/javascript", headers={"Cache-Control": "no-store, max-age=0"})
    raise HTTPException(status_code=404, detail="Motion script not found")


@app.get("/train")
async def train_page(request: Request):
    """智能体训练页面"""
    from fastapi.responses import FileResponse, RedirectResponse

    # 旧版训练页曾被浏览器长期缓存。把视觉版本放进地址本身，确保首访、
    # 回退和书签访问都加载同一套界面，同时保留 level / focus 等业务参数。
    if request.query_params.get("ui") != UI_VERSION:
        query_items = [
            (key, value)
            for key, value in request.query_params.multi_items()
            if key != "ui"
        ]
        query_items.append(("ui", UI_VERSION))
        return RedirectResponse(
            url=f"/train?{urlencode(query_items)}",
            status_code=307,
            headers={"Cache-Control": "no-store, max-age=0"},
        )

    train_path = STATIC_DIR / "train.html"
    if train_path.exists():
        return FileResponse(train_path, headers={"Cache-Control": "no-store, max-age=0"})
    return {"message": "训练页面不存在", "hint": "请检查 static/train.html"}


@app.get("/study")
async def study_page():
    """条文学习页面"""
    from fastapi.responses import FileResponse
    study_path = STATIC_DIR / "study.html"
    if study_path.exists():
        return FileResponse(study_path, headers={"Cache-Control": "no-store, max-age=0"})
    return {"message": "学习页面不存在", "hint": "请检查 static/study.html"}


@app.get("/showcase")
async def showcase_page():
    """金匮要略 Showcase 展示页"""
    from fastapi.responses import FileResponse
    showcase_path = STATIC_DIR / "showcase.html"
    if showcase_path.exists():
        return FileResponse(showcase_path)
    return {"message": "Showcase 页面不存在", "hint": "请检查 static/showcase.html"}
