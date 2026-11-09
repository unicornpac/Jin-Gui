"""其余 HTTP 层测试 —— 合并自原 api_routes 的页面/统计/错误处理与 analysis 文件。"""
import os

import pytest
from sqlalchemy.orm import sessionmaker

from app.models import ClassicText, MedicalCase, TrainingSession

ADMIN_AUTH = ("admin", os.environ.get("ADMIN_PASSWORD", "jingui2026"))


class TestPages:
    """静态页面可访问性"""

    @pytest.mark.parametrize("path", ["/user", "/train", "/study", "/docs"])
    def test_page_ok(self, client, path):
        assert client.get(path).status_code == 200

    def test_root_requires_auth(self, client):
        resp = client.get("/")
        assert resp.status_code == 401
        assert resp.headers.get("www-authenticate") == "Basic"


class TestAuthenticationBoundaries:
    """管理 API 返回 JSON 401 而不触发浏览器密码框"""

    def test_admin_api_401_has_no_basic_challenge(self, client):
        resp = client.get("/api/agent/sessions")
        assert resp.status_code == 401
        assert "www-authenticate" not in resp.headers
        assert resp.json()["detail"] == "需要管理员认证"

    def test_admin_api_accepts_basic_credentials(self, client):
        assert client.get("/api/agent/sessions", auth=ADMIN_AUTH).status_code == 200


class TestPublicStats:
    """公开首页只读聚合统计"""

    def test_public_stats_returns_aggregates(self, client, engine):
        Session = sessionmaker(bind=engine)
        db = Session()
        try:
            db.add(ClassicText(source_book="《伤寒论》", content="太阳之为病"))
            db.add(MedicalCase(title="测试病案", content="内容", difficulty_level="初级"))
            db.add_all([
                TrainingSession(difficulty_level="初级", score="80分"),
                TrainingSession(difficulty_level="中级", score="90"),
                TrainingSession(difficulty_level="高级", score="未评分"),
            ])
            db.commit()
        finally:
            db.close()

        resp = client.get("/api/agent/public-stats")
        assert resp.status_code == 200
        assert resp.json() == {
            "text_count": 1,
            "case_count": 1,
            "session_count": 3,
            "average_score": 85.0,
        }


class TestErrorHandling:
    """全局异常处理"""

    def test_404_unknown_route(self, client):
        assert client.get("/api/nonexistent").status_code == 404

    def test_422_validation_error_not_500(self, client):
        """参数校验失败返回 422 而非 500"""
        resp = client.post("/api/agent/session/1/message", json={})
        assert resp.status_code == 422
        assert "detail" in resp.json()

    def test_404_http_exception_not_masked_as_500(self, client):
        """HTTPException 不应被全局处理器吞成 500"""
        resp = client.get("/api/agent/session/99999", auth=ADMIN_AUTH)
        assert resp.status_code == 404


class TestAnalysisApi:
    """条文分析接口"""

    def test_status_and_models_require_admin(self, client):
        """provider 名称与模型列表属于基础设施信息，不对公网开放"""
        assert client.get("/api/analysis/status").status_code == 401
        assert client.get("/api/analysis/models").status_code == 401
        assert client.get("/api/analysis/status", auth=ADMIN_AUTH).status_code in (200, 503)

    def test_query_without_ai_key_degrades_gracefully(self, client):
        resp = client.post("/api/analysis/query", json={
            "text": "太阳之为病，脉浮，头项强痛而恶寒。"
        })
        assert resp.status_code in (200, 503)
        if resp.status_code == 200:
            assert resp.json()["analysis_result"]

    def test_history_is_public_and_delete_requires_admin(self, client):
        assert client.get("/api/analysis/history").status_code == 200
        assert client.delete("/api/analysis/log/1").status_code == 401


class TestFeedback:
    """用户反馈：提交公开、管理需认证"""

    def test_submit_and_list(self, client):
        resp = client.post("/api/feedback/", json={
            "category": "功能建议", "content": "希望增加复习模式",
        })
        assert resp.status_code == 201

        assert client.get("/api/feedback/").status_code == 401
        listed = client.get("/api/feedback/", auth=ADMIN_AUTH).json()
        assert len(listed) == 1 and listed[0]["content"] == "希望增加复习模式"

    def test_update_and_delete(self, client):
        client.post("/api/feedback/", json={"category": "bug反馈", "content": "训练页刷新会丢进度"})
        feedback_id = client.get("/api/feedback/", auth=ADMIN_AUTH).json()[0]["id"]

        assert client.put(f"/api/feedback/{feedback_id}",
                          json={"status": "resolved"}).status_code == 401
        updated = client.put(f"/api/feedback/{feedback_id}",
                             json={"status": "resolved", "admin_note": "已记录"},
                             auth=ADMIN_AUTH)
        assert updated.status_code == 200

        assert client.delete(f"/api/feedback/{feedback_id}").status_code == 401
        assert client.delete(f"/api/feedback/{feedback_id}", auth=ADMIN_AUTH).status_code == 200
