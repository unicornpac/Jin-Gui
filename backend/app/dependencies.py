"""
共享依赖 —— 认证、频率限制
"""
import hashlib
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

    def _get_key(self, request: Request, actor: Optional[str] = None) -> str:
        """以「身份 + 方法 + 路由」为 key。

        actor 为空时退回客户端 IP。校园网、机房这类出口 NAT 后，成百上千个
        学生会共享同一个 IP：按 IP 计数会把整批人当成一个用户，额度被互相挤占，
        第 11 个人点「开始训练」就会收到 429。训练类端点因此优先按会话令牌/学号
        计数（见下方 limit_agent_*），只有管理类端点继续按 IP 限流。
        """
        import re

        subject = actor or (request.client.host if request.client else "unknown")
        route = request.url.path
        # 将数字 ID 替换为占位符，聚合同类端点的计数
        route = re.sub(r'/\d+', '/{id}', route)
        return f"{subject}:{request.method}:{route}"

    def is_allowed(self, request: Request, max_requests: int, window_seconds: int,
                   actor: Optional[str] = None) -> tuple[bool, int]:
        """返回 (是否允许, 剩余次数)"""
        key = self._get_key(request, actor)
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


# ==================== 身份标识 ====================
# 训练端点按「人」限流，管理端点按「IP」限流。
# 身份值只以短哈希入 key：内存里不留令牌明文，日志也不会带出学号。

def _digest_actor(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _header_actor(request: Request) -> Optional[str]:
    """会话归属令牌（X-Session-Token）——训练对话与结算的主身份。"""
    token = (request.headers.get("X-Session-Token") or "").strip()
    return f"tok:{_digest_actor(token)}" if token else None


def _ip_actor(request: Request) -> str:
    return f"ip:{request.client.host if request.client else 'unknown'}"


# 预设限制策略（作为便捷函数）
def limit_agent_message(request: Request):
    """训练对话：一人一分钟 30 条。同一出口 NAT 的学生互不影响。"""
    actor = _header_actor(request) or _ip_actor(request)
    return get_limiter().is_allowed(request, 30, 60, actor=actor)[0] or _raise_429(30, 60)


async def limit_agent_start(request: Request):
    """开始训练按学号计数，结束评价按会话令牌计数，都缺失时退回 IP。"""
    actor = None
    if request.url.path.endswith("/session/start"):
        # 学号在请求体里，依赖执行早于业务参数绑定，这里主动读一次（body 有缓存）
        try:
            payload = await request.json()
        except Exception:
            payload = None
        student_id = str((payload or {}).get("student_id") or "").strip() if isinstance(payload, dict) else ""
        if student_id:
            actor = f"stu:{_digest_actor(student_id)}"
    actor = actor or _header_actor(request) or _ip_actor(request)
    return get_limiter().is_allowed(request, 10, 60, actor=actor)[0] or _raise_429(10, 60)


def limit_upload(request: Request):
    """上传仍按 IP：管理端单人操作，且要防同一出口的批量刷。"""
    return get_limiter().is_allowed(request, 20, 3600, actor=_ip_actor(request))[0] or _raise_429(20, 3600)


def limit_analysis(request: Request):
    """AI 分析仍是管理端功能，按 IP 限流。"""
    return get_limiter().is_allowed(request, 10, 60, actor=_ip_actor(request))[0] or _raise_429(10, 60)


def _raise_429(max_req: int, window: int):
    unit = "秒" if window < 120 else ("分" if window < 7200 else "时")
    val = window if window < 120 else (window // 60 if window < 7200 else window // 3600)
    raise HTTPException(
        status_code=429,
        detail=f"请求过于频繁，请稍后重试（限制 {max_req} 次/{val}{unit}）",
        headers={"Retry-After": str(window)},
    )
