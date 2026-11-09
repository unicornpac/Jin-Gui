"""训练会话归属令牌。

设计取舍
--------
本系统没有用户体系（`student_id` 由前端生成、可伪造），因此用「会话 id + 服务端密钥」
派生的令牌来证明"这个会话是我创建的"，而不是引入 JWT：

- **无状态**：令牌由 `HMAC-SHA256(session_id)` 派生，不落库、不需要 Alembic 迁移，
  同一个会话可重复派生出相同令牌。
- **不可枚举**：没有服务端密钥就无法从 id 推导出其他会话的令牌，因此无法接管他人训练。
- **失效方式**：删除会话即 404；轮换 `SESSION_SECRET` 会使所有旧令牌失效。

密钥来源优先级：`SESSION_SECRET` → `ADMIN_PASSWORD`。两者都未配置时使用进程级随机密钥
（重启即失效），绝不退化成可预测的固定值。
"""
import hashlib
import hmac
import os
import secrets
from typing import Optional

# 未配置任何密钥时的进程级随机密钥：进程存活期间稳定，重启后旧令牌全部失效。
_EPHEMERAL_SECRET: bytes = secrets.token_bytes(32)


def _secret() -> bytes:
    configured = (os.environ.get("SESSION_SECRET") or os.environ.get("ADMIN_PASSWORD") or "").strip()
    if configured:
        return configured.encode("utf-8")
    return _EPHEMERAL_SECRET


def issue_session_token(session_id: int) -> str:
    """为指定会话派生归属令牌（同一进程内幂等）。"""
    mac = hmac.new(_secret(), str(int(session_id)).encode("utf-8"), hashlib.sha256)
    return mac.hexdigest()[:32]


def verify_session_token(session_id: int, token: Optional[str]) -> bool:
    """恒定时间校验归属令牌。"""
    if not token:
        return False
    expected = issue_session_token(session_id)
    given = token.strip()
    return hmac.compare_digest(expected, given)
