"""安全回归测试 —— 第一批 P0 修复的守护用例。

覆盖：
- `/health`、`/live`、`/ready` 的状态码与返回体形态（P0-6）
- 病案读接口不再泄漏标准答案（P0-5）
- 训练会话归属令牌校验（P0-7）
- 上传文件名的路径穿越与扩展名白名单（P0-8）
- `text_verifier` 的 logger 与降级（P1-7）
- 反馈类别枚举收口（P0-9 配套）
"""
import io
import os

import pytest
from unittest.mock import MagicMock

from app.services.session_token import issue_session_token

ADMIN_AUTH = ("admin", os.environ.get("ADMIN_PASSWORD", "jingui2026"))


def _make_case(**kw):
    return {
        "title": "湿病——麻黄加术汤证",
        "content": "患者淋雨后全身关节疼痛沉重，恶寒发热无汗。",
        "symptoms": "身痛重着、恶寒发热、无汗",
        "diagnosis": "湿病（表湿证）",
        "prescription": "麻黄加术汤",
        "difficulty_level": "初级",
        "teaching_points": "辨病关键：身痛重着=表湿",
        "correct_answer": "辨病：湿病。定治：麻黄加术汤。",
        **kw,
    }


class _OkSession:
    def execute(self, *args, **kwargs):
        return None

    def close(self):
        pass


class _BrokenSession:
    def execute(self, *args, **kwargs):
        raise RuntimeError("db down")

    def close(self):
        pass


class TestHealthProbes:
    """P0-6：健康检查必须真的改变状态码，且返回体是对象。"""

    def test_health_returns_object_body(self, client, monkeypatch):
        monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
        import app.database as database
        monkeypatch.setattr(database, "SessionLocal", lambda: _OkSession())

        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, dict), "修复前返回体被编码成 [body, status] 数组"
        assert body["status"] == "ok"
        assert body["db"] == "connected"

    def test_health_returns_503_when_db_down(self, client, monkeypatch):
        monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
        import app.database as database
        monkeypatch.setattr(database, "SessionLocal", lambda: _BrokenSession())

        resp = client.get("/health")
        assert resp.status_code == 503
        assert resp.json()["status"] == "degraded"

    def test_live_is_always_ok(self, client):
        resp = client.get("/live")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_ready_matches_health(self, client, monkeypatch):
        monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
        import app.database as database
        monkeypatch.setattr(database, "SessionLocal", lambda: _OkSession())

        assert client.get("/ready").status_code == 200


class TestCaseAnswerExposure:
    """P0-5：公开病案接口不得下发诊断、方剂、教学要点与参考答案。"""

    LEAKY_FIELDS = ("correct_answer", "teaching_points", "diagnosis", "prescription")

    def test_public_list_hides_answers(self, client):
        client.post("/api/cases/", json=_make_case(), auth=ADMIN_AUTH)

        row = client.get("/api/cases/").json()[0]
        for field in self.LEAKY_FIELDS:
            assert field not in row, f"公开列表泄漏了 {field}"

    def test_public_detail_hides_answers(self, client):
        case_id = client.post("/api/cases/", json=_make_case(), auth=ADMIN_AUTH).json()["id"]

        body = client.get(f"/api/cases/{case_id}").json()
        for field in self.LEAKY_FIELDS:
            assert field not in body, f"公开详情泄漏了 {field}"

    def test_admin_endpoints_require_auth(self, client):
        case_id = client.post("/api/cases/", json=_make_case(), auth=ADMIN_AUTH).json()["id"]
        assert client.get("/api/cases/admin/").status_code == 401
        assert client.get(f"/api/cases/admin/{case_id}").status_code == 401

    def test_admin_endpoints_return_answers(self, client):
        case_id = client.post("/api/cases/", json=_make_case(), auth=ADMIN_AUTH).json()["id"]

        listed = client.get("/api/cases/admin/", auth=ADMIN_AUTH).json()
        assert listed[0]["correct_answer"]
        detail = client.get(f"/api/cases/admin/{case_id}", auth=ADMIN_AUTH).json()
        assert detail["teaching_points"]


class TestSessionOwnership:
    """P0-7：训练会话必须凭归属令牌操作，否则可枚举 id 取答案。"""

    @pytest.fixture
    def session_id(self, engine):
        from sqlalchemy.orm import sessionmaker
        from app.models import MedicalCase, TrainingSession

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

    def test_message_without_token_is_403(self, client, session_id):
        resp = client.post(f"/api/agent/session/{session_id}/message", json={"content": "你好"})
        assert resp.status_code == 403

    def test_message_with_foreign_token_is_403(self, client, session_id):
        resp = client.post(
            f"/api/agent/session/{session_id}/message",
            json={"content": "你好"},
            headers={"X-Session-Token": issue_session_token(session_id + 1)},
        )
        assert resp.status_code == 403

    def test_evaluate_without_token_is_403(self, client, session_id):
        assert client.post(f"/api/agent/session/{session_id}/evaluate").status_code == 403

    def test_detail_requires_admin(self, client, session_id):
        assert client.get(f"/api/agent/session/{session_id}").status_code == 401


class TestUploadPathTraversal:
    """P0-8：落盘文件名不得包含客户端提供的路径成分。"""

    def test_filename_is_sanitised(self, client, tmp_path, monkeypatch):
        import app.routers.documents as docs

        monkeypatch.setattr(docs, "UPLOAD_DIR", str(tmp_path))

        files = {"file": ("../../evil.txt", io.BytesIO(b"x"), "text/plain")}
        resp = client.post("/api/documents/upload", files=files, auth=ADMIN_AUTH)
        assert resp.status_code == 200

        written = list(tmp_path.iterdir())
        assert len(written) == 1, "应只在目标目录内落盘一个文件"
        assert written[0].parent == tmp_path, "文件逃出了上传目录"
        assert written[0].suffix == ".txt"
        assert "evil" not in written[0].name, "原始文件名不应参与落盘路径"

    def test_disallowed_extension_rejected(self, client, tmp_path, monkeypatch):
        import app.routers.documents as docs

        monkeypatch.setattr(docs, "UPLOAD_DIR", str(tmp_path))

        files = {"file": ("payload.sh", io.BytesIO(b"#!/bin/sh"), "text/plain")}
        resp = client.post("/api/documents/upload", files=files, auth=ADMIN_AUTH)
        assert resp.status_code == 400
        assert list(tmp_path.iterdir()) == []


class TestVerifierLogging:
    """P1-7：`logger` 未定义会让异常分支抛 NameError。"""

    def test_module_has_logger(self):
        import app.services.text_verifier as tv

        assert hasattr(tv, "logger")

    def test_classify_failure_degrades_instead_of_raising(self):
        import app.services.text_verifier as tv

        verifier = tv.TextVerifier()
        verifier.client = MagicMock()
        verifier.client.chat.completions.create.side_effect = RuntimeError("llm down")

        class _FakeText:
            content = "太阳之为病，脉浮"
            source_book = "《伤寒论》"
            chapter = "辨太阳病脉证并治"
            article_number = 1

        # 修复前这里会抛 NameError 并冒到路由变成 500
        assert verifier.classify_text(_FakeText()) == {}


class TestFeedbackValidation:
    """公开反馈接口的类别必须收口，否则会作为渲染内容进入管理端。"""

    def test_invalid_category_rejected(self, client):
        resp = client.post(
            "/api/feedback/",
            json={"category": "<img src=x onerror=alert(1)>", "content": "测试内容够长"},
        )
        assert resp.status_code == 422

    def test_valid_category_accepted(self, client):
        resp = client.post(
            "/api/feedback/",
            json={"category": "功能建议", "content": "希望增加复习模式"},
        )
        assert resp.status_code == 201
