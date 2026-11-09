"""训练会话 API 与消息链路测试 —— 合并自原 api_routes（agent 部分）与 agent_message_flow。"""
import json
import os
import sys
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import sessionmaker

from app.models import MedicalCase, SessionMessage, TrainingSession
from app.services.agent_service import DASHSCOPE_COMPATIBLE_BASE_URL, TrainingAgent, get_agent
from app.services.session_token import issue_session_token

ADMIN_AUTH = ("admin", os.environ.get("ADMIN_PASSWORD", "jingui2026"))


class TestSessionLifecycle:
    """HTTP 层：创建、发消息、评价"""

    def test_start_session_returns_token_and_opening(self, client):
        mock_agent = MagicMock()
        mock_agent.create_session.return_value = (
            MagicMock(id=1, difficulty_level="初级", case=MagicMock(title="湿病")),
            "医生你好，我最近全身关节疼……",
        )
        client.app.dependency_overrides[get_agent] = lambda: mock_agent
        try:
            resp = client.post("/api/agent/session/start", json={
                "difficulty_level": "初级", "student_id": "test_user",
            })
            assert resp.status_code == 200
            data = resp.json()
            assert data["session_id"] == 1
            assert data["agent_message"]
            assert data["session_token"] == issue_session_token(1)
        finally:
            client.app.dependency_overrides.pop(get_agent, None)

    def test_start_session_missing_difficulty(self, client):
        assert client.post("/api/agent/session/start", json={}).status_code >= 400

    def test_start_session_agent_error(self, client):
        mock_agent = MagicMock()
        mock_agent.create_session.side_effect = ValueError("数据库中没有病案")
        client.app.dependency_overrides[get_agent] = lambda: mock_agent
        try:
            resp = client.post("/api/agent/session/start", json={"difficulty_level": "初级"})
            assert resp.status_code == 400
        finally:
            client.app.dependency_overrides.pop(get_agent, None)

    def test_send_message_session_not_found(self, client):
        mock_agent = MagicMock()
        mock_agent.process_message.side_effect = ValueError("会话 99999 不存在")
        client.app.dependency_overrides[get_agent] = lambda: mock_agent
        try:
            resp = client.post(
                "/api/agent/session/99999/message",
                json={"content": "你好"},
                headers={"X-Session-Token": issue_session_token(99999)},
            )
            assert resp.status_code == 400
        finally:
            client.app.dependency_overrides.pop(get_agent, None)

    def test_evaluation_returns_safety_feedback(self, client, engine):
        Session = sessionmaker(bind=engine)
        db = Session()
        try:
            case = MedicalCase(title="测试病案", content="测试内容",
                               prescription="测试方", difficulty_level="初级")
            db.add(case)
            db.commit()
            session = TrainingSession(student_id="test_user", difficulty_level="初级",
                                      case_id=case.id, status="active")
            db.add(session)
            db.commit()

            mock_agent = MagicMock()
            mock_agent.evaluate_session.return_value = {
                "score": "0",
                "evaluation": '{"综合评分": 0}',
                "decision_path": "测试路径",
                "related_texts": [],
                "safety_feedback": {
                    "level": "critical", "title": "严重用药安全风险",
                    "summary": "训练安全红线触发", "details": [],
                },
            }
            client.app.dependency_overrides[get_agent] = lambda: mock_agent
            try:
                resp = client.post(
                    f"/api/agent/session/{session.id}/evaluate",
                    headers={"X-Session-Token": issue_session_token(session.id)},
                )
                assert resp.status_code == 200
                assert resp.json()["safety_feedback"]["level"] == "critical"
            finally:
                client.app.dependency_overrides.pop(get_agent, None)
        finally:
            db.close()


class TestMessageContext:
    """消息进模型的方式"""

    def test_current_input_is_sent_once(self, agent, db_session, active_session):
        agent._call_llm = MagicMock(return_value="我这两天就是觉得关节发沉。")

        agent.process_message(db_session, active_session.id, "我想先问一下你哪里不舒服？")

        call = agent._call_llm.call_args
        history = call.args[1]
        current_input = call.args[2]
        assert current_input == "我想先问一下你哪里不舒服？"
        assert all(m["content"] != current_input for m in history)

    def test_progress_check_runs_at_configured_interval(self, agent):
        agent.client = object()
        agent.progress_check_interval = 3
        progress = {stage: False for stage in agent.STAGES}
        turns = lambda n: [{"role": "user", "content": "继续问诊"}] * n

        assert agent._should_check_ai_progress(turns(2), progress) is False
        assert agent._should_check_ai_progress(turns(3), progress) is True
        assert agent._should_check_ai_progress(turns(4), progress) is False

    def test_completed_status_is_persisted(self, agent, db_session, active_session):
        with patch.object(agent, "_call_llm", return_value="那我听你的。"), \
             patch.object(agent, "_should_end_session", return_value=True):
            _, _, status, _ = agent.process_message(db_session, active_session.id, "我给你开方调理。")

        db_session.refresh(active_session)
        assert status == "completed"
        assert active_session.status == "completed"
        assert active_session.ended_at is not None


class TestModelConfiguration:
    """AI 端点配置"""

    def test_dashscope_key_uses_openai_compatible_endpoint(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
        monkeypatch.delenv("AI_MODEL", raising=False)
        monkeypatch.setenv("DASHSCOPE_API_KEY", "dashscope-test-key")
        monkeypatch.setenv("AI_TIMEOUT_SECONDS", "30")

        captured = {}
        fake_openai = ModuleType("openai")

        def fake_client(**options):
            captured.update(options)
            return object()

        fake_openai.OpenAI = fake_client
        monkeypatch.setitem(sys.modules, "openai", fake_openai)

        configured = TrainingAgent()

        assert configured.provider == "dashscope"
        assert configured.model == "qwen-turbo"
        assert configured.base_url == DASHSCOPE_COMPATIBLE_BASE_URL
        assert captured["api_key"] == "dashscope-test-key"
        assert captured["timeout"] == 30
        assert captured["max_retries"] == 0

    def test_missing_key_disables_client(self, monkeypatch):
        for key in ("OPENAI_API_KEY", "DASHSCOPE_API_KEY", "OPENAI_BASE_URL"):
            monkeypatch.setenv(key, "")
        configured = TrainingAgent()
        assert configured.client is None
        assert "暂未就绪" in configured._fallback_response() or configured.client is None

class TestSessionResumeAccess:
    """会话详情：管理员，或持有效 X-Session-Token 的会话持有者。"""

    @pytest.fixture
    def session_id(self, engine):
        from sqlalchemy.orm import sessionmaker

        Session = sessionmaker(bind=engine)
        db = Session()
        try:
            case = MedicalCase(title="测试病案", content="测试内容", difficulty_level="初级")
            db.add(case)
            db.commit()
            session = TrainingSession(difficulty_level="初级", case_id=case.id, status="active")
            db.add(session)
            db.commit()
            return session.id
        finally:
            db.close()

    def test_owner_reads_with_token(self, client, session_id):
        resp = client.get(
            f"/api/agent/session/{session_id}",
            headers={"X-Session-Token": issue_session_token(session_id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "active"
        assert body["difficulty_level"] == "初级"

    def test_no_credentials_is_401(self, client, session_id):
        assert client.get(f"/api/agent/session/{session_id}").status_code == 401

    def test_foreign_token_is_401(self, client, session_id):
        resp = client.get(
            f"/api/agent/session/{session_id}",
            headers={"X-Session-Token": issue_session_token(session_id + 1)},
        )
        assert resp.status_code == 401

    def test_admin_still_reads_any_session(self, client, session_id):
        assert client.get(
            f"/api/agent/session/{session_id}", auth=ADMIN_AUTH
        ).status_code == 200

    def test_student_id_length_is_validated(self, client):
        resp = client.post(
            "/api/agent/session/start",
            json={"difficulty_level": "初级", "student_id": "x" * 40},
        )
        assert resp.status_code == 422
