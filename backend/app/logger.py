"""
结构化日志模块 — 替代全局 print()。

用法:
    from app.logger import get_logger
    logger = get_logger(__name__)
    logger.info("用户登录", extra={"user": "admin"})

生产环境: 设置 LOG_FORMAT=json 输出 JSON 格式（含时间戳、级别、模块、请求ID）
开发环境: 默认人类可读格式
"""
import logging
import os
import sys
import json
import uuid
from datetime import datetime, timezone
from contextvars import ContextVar

# 请求上下文：Middleware 注入 X-Request-ID
_request_id: ContextVar[str] = ContextVar("request_id", default="-")


class StructuredFormatter(logging.Formatter):
    """JSON 结构化格式器（生产环境）"""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "level": record.levelname,
            "module": record.name,
            "msg": record.getMessage(),
            "req": _request_id.get(),
        }
        if record.exc_info and record.exc_info[1]:
            entry["error"] = str(record.exc_info[1])
        return json.dumps(entry, ensure_ascii=False)


class ReadableFormatter(logging.Formatter):
    """可读格式器（开发环境）"""

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        req = _request_id.get()
        req_tag = f"[{req[:8]}]" if req and req != "-" else ""
        return f"{ts} {record.levelname:<5} {req_tag} [{record.name}] {record.getMessage()}"


def get_logger(name: str) -> logging.Logger:
    """获取模块级 logger。首次调用时自动配置根 logger。"""
    _ensure_configured()
    return logging.getLogger(name)


_config_done = False


def _ensure_configured():
    global _config_done
    if _config_done:
        return
    _config_done = True

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    # 清除已有 handler（避免重复）
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    fmt = os.environ.get("LOG_FORMAT", "").lower()
    if fmt == "json":
        handler.setFormatter(StructuredFormatter())
    else:
        handler.setFormatter(ReadableFormatter())

    root.addHandler(handler)


def set_request_id(rid: str) -> None:
    """设置当前请求的 Request ID（由 middleware 调用）"""
    _request_id.set(rid)
