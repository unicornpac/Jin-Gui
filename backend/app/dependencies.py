"""
共享依赖 —— 认证、频率限制
"""
import os
import secrets
import time
import threading
from collections import defaultdict
from typing import Optional
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials

api_security = HTTPBasic(auto_error=False)
page_security = HTTPBasic()


def get_admin_password() -> str:
    """管理员密码只从环境变量读取；未配置时返回空串（任何密码都不通过）。

    刻意不再提供内置默认值：默认口令一旦生效，所有部署就共享同一个入口。
    需要登录管理端时必须显式设置 ADMIN_PASSWORD（见 README 环境变量表）。
    """
    return (os.environ.get("ADMIN_PASSWORD") or "").strip()


def _password_is_valid(credentials: Optional[HTTPBasicCredentials]) -> bool:
    """以恒定时间比较管理员密码。"""
    if credentials is None:
        return False
    correct = get_admin_password()
    if not correct:
        return False
    return secrets.compare_digest(credentials.password.encode(), correct.encode())


def verify_admin(credentials: Optional[HTTPBasicCredentials] = Depends(api_security)):
    """验证管理 API；失败时只返回 JSON，不触发浏览器原生密码框。"""
    if not _password_is_valid(credentials):
        raise HTTPException(status_code=401, detail="需要管理员认证")
    return credentials.username


def verify_admin_optional(
    credentials: Optional[HTTPBasicCredentials] = Depends(api_security),
) -> bool:
    """不强制要求认证，只返回“是否具备管理员身份”。

    供“管理员或持有效会话令牌”二选一的端点使用（例如学生刷新后读取自己的训练详情）。
    """
    return _password_is_valid(credentials)


def verify_admin_page(credentials: HTTPBasicCredentials = Depends(page_security)):
    """验证管理端页面；失败时发出 Basic challenge，让浏览器显示登录框。"""
    if not _password_is_valid(credentials):
        raise HTTPException(
            status_code=401,
            detail="密码错误",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


# ==================== 简易速率限制器 ====================

class SimpleRateLimiter:
    """基于内存滑动窗口的速率限制器（无需外部依赖）"""

    # 每处理这么多次请求做一次空 key 回收，防止 key 只增不减
    _PRUNE_INTERVAL = 1000
    # key 的最后活跃时间早于该秒数即视为可回收
    _STALE_SECONDS = 3600

    def __init__(self):
        self._windows: dict[str, list[float]] = {}
        self._lock = threading.Lock()
        self._calls = 0

    def _get_key(self, request: Request) -> str:
        """以 IP + 路由为 key"""
        client_ip = request.client.host if request.client else "unknown"
        # 取路由前缀进行限流（如 POST /api/agent/session/xxx/message → /api/agent/session/message）
        route = request.url.path
        # 将数字 ID 替换为占位符，聚合同类端点的计数
        import re
        route = re.sub(r'/\d+', '/{id}', route)
        return f"{client_ip}:{request.method}:{route}"

    def is_allowed(self, request: Request, max_requests: int, window_seconds: int) -> tuple[bool, int]:
        """返回 (是否允许, 剩余次数)"""
        key = self._get_key(request)
        now = time.time()
        cutoff = now - window_seconds

        with self._lock:
            # 只保留窗口内的记录
            times = [t for t in self._windows.get(key, []) if t > cutoff]

            if len(times) >= max_requests:
                self._windows[key] = times
                return False, 0

            times.append(now)
            self._windows[key] = times
            self._maybe_prune(now)
            return True, max_requests - len(times)

    def _maybe_prune(self, now: float) -> None:
        """定期回收长期不活跃的 key，避免 key 数量只增不减。"""
        self._calls += 1
        if self._calls % self._PRUNE_INTERVAL:
            return
        stale = [
            k for k, v in self._windows.items()
            if not v or v[-1] < now - self._STALE_SECONDS
        ]
        for k in stale:
            del self._windows[k]

    def limit(self, max_requests: int, window_seconds: int = 60):
        """返回 FastAPI 依赖函数"""

        def _limiter(request: Request):
            allowed, remaining = self.is_allowed(request, max_requests, window_seconds)
            if not allowed:
                retry_after = window_seconds
                raise HTTPException(
                    status_code=429,
                    detail=f"请求过于频繁，请 {retry_after} 秒后重试（限制 {max_requests} 次/{window_seconds}秒）",
                    headers={"Retry-After": str(retry_after), "X-RateLimit-Remaining": "0"},
                )
            return remaining

        return Depends(_limiter)


# 全局实例
_limiter = None


def get_limiter() -> SimpleRateLimiter:
    global _limiter
    if _limiter is None:
        _limiter = SimpleRateLimiter()
    return _limiter


# 预设限制策略（作为便捷函数）
def limit_agent_message(request: Request):
    return get_limiter().is_allowed(request, 30, 60)[0] or _raise_429(30, 60)


def limit_agent_start(request: Request):
    return get_limiter().is_allowed(request, 10, 60)[0] or _raise_429(10, 60)


def limit_upload(request: Request):
    return get_limiter().is_allowed(request, 20, 3600)[0] or _raise_429(20, 3600)


def limit_analysis(request: Request):
    return get_limiter().is_allowed(request, 10, 60)[0] or _raise_429(10, 60)


def _raise_429(max_req: int, window: int):
    unit = "秒" if window < 120 else ("分" if window < 7200 else "时")
    val = window if window < 120 else (window // 60 if window < 7200 else window // 3600)
    raise HTTPException(
        status_code=429,
        detail=f"请求过于频繁，请稍后重试（限制 {max_req} 次/{val}{unit}）",
        headers={"Retry-After": str(window)},
    )
