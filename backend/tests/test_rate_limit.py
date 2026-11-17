"""限流身份维度回归测试。

背景：限流 key 原本只有「客户端 IP + 方法 + 路由」。校园网、机房这类出口 NAT 后，
几十上百个学生对服务端是同一个 IP，额度被互相挤占——第 11 个人点「开始训练」
就会收到 429，且和负载无关。

现改为：训练端点按学号 / 会话令牌计数，管理端点仍按 IP。本文件守护四件事：
1. 不同学号互不挤占；同一学号才会耗尽额度；
2. 不同会话令牌互不挤占；
3. 缺身份时回退 IP，不至于完全不限流；
4. 路由里的数字 ID 仍被归一，换会话绕不过限制。
"""
import asyncio
import os
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.dependencies import (
    SimpleRateLimiter,
    _header_actor,
    _ip_actor,
    get_limiter,
    limit_agent_start,
)
from app.services.agent_service import get_agent

ADMIN_AUTH = ("admin", os.environ.get("ADMIN_PASSWORD", "jingui2026"))


class _FakeRequest:
    """最小 Request 替身：只带限流与身份解析用到的字段。"""

    def __init__(self, path, headers=None, ip="10.0.0.5", method="POST", body=None):
        self.url = SimpleNamespace(path=path)
        self.method = method
        self.headers = headers or {}
        self.client = SimpleNamespace(host=ip)
        self._body = body

    async def json(self):
        if self._body is None:
            raise ValueError("no body")
        return self._body


def _reset():
    get_limiter()._windows.clear()


def _start(student_id=None):
    body = {"difficulty_level": "初级"}
    if student_id:
        body["student_id"] = student_id
    return _FakeRequest("/api/agent/session/start", body=body)


class TestIdentityKey:
    def test_token_identity_is_hashed_not_plaintext(self):
        req = _FakeRequest("/api/agent/session/7/message", {"X-Session-Token": "plain-token"})
        actor = _header_actor(req)
        assert actor.startswith("tok:")
        assert "plain-token" not in actor

    def test_route_digits_are_normalised(self):
        limiter = SimpleRateLimiter()
        r = _FakeRequest("/api/agent/session/7/message", {"X-Session-Token": "t"})
        key = limiter._get_key(r, _header_actor(r))
        assert "/api/agent/session/{id}/message" in key

    def test_ip_fallback_when_no_identity(self):
        req = _FakeRequest("/api/agent/session/1/message")
        assert _header_actor(req) is None
        assert _ip_actor(req) == "ip:10.0.0.5"


class TestMessageLimitByToken:
    def test_two_tokens_do_not_share_quota(self):
        limiter = SimpleRateLimiter()
        r1 = _FakeRequest("/api/agent/session/1/message", {"X-Session-Token": "token-a"})
        r2 = _FakeRequest("/api/agent/session/2/message", {"X-Session-Token": "token-b"})
        a1, a2 = _header_actor(r1), _header_actor(r2)
        assert a1 != a2

        for _ in range(30):
            assert limiter.is_allowed(r1, 30, 60, actor=a1)[0] is True
        assert limiter.is_allowed(r1, 30, 60, actor=a1)[0] is False
        # 同一出口 IP 的另一个人不受影响
        assert limiter.is_allowed(r2, 30, 60, actor=a2)[0] is True


class TestStartLimitByStudent:
    def test_distinct_students_do_not_share_quota(self):
        _reset()
        # 12 个人在同一 IP 上依次开始训练，全部通过（旧逻辑第 11 人必 429）
        for i in range(12):
            assert asyncio.run(limit_agent_start(_start("2024%04d" % i))) is True

    def test_same_student_is_limited(self):
        _reset()
        for _ in range(10):
            asyncio.run(limit_agent_start(_start("20240001")))
        with pytest.raises(HTTPException) as exc:
            asyncio.run(limit_agent_start(_start("20240001")))
        assert exc.value.status_code == 429

    def test_no_identity_falls_back_to_ip(self):
        _reset()
        for _ in range(10):
            asyncio.run(limit_agent_start(_start()))
        with pytest.raises(HTTPException) as exc:
            asyncio.run(limit_agent_start(_start()))
        assert exc.value.status_code == 429


class TestHttpLayer:
    def test_eleven_students_start_within_a_minute(self, client):
        """HTTP 层复现线上场景：同一客户端 IP，12 个不同学号连续开始训练。"""
        _reset()
        mock_agent = MagicMock()
        mock_agent.create_session.return_value = (
            MagicMock(id=1, difficulty_level="初级", case=MagicMock(title="湿病")),
            "医生你好，我最近全身关节疼……",
        )
        client.app.dependency_overrides[get_agent] = lambda: mock_agent
        try:
            for i in range(12):
                resp = client.post(
                    "/api/agent/session/start",
                    json={"difficulty_level": "初级", "student_id": "S%03d" % i},
                )
                assert resp.status_code == 200, resp.text
        finally:
            client.app.dependency_overrides.pop(get_agent, None)
