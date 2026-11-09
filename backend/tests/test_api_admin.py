"""管理端 API 集成测试 —— 合并自原 cases / texts / documents 三个文件。

约定：写操作一律要求管理员认证；读操作按是否含敏感数据区分。
"""
import io
import os

import pytest

ADMIN_AUTH = ("admin", os.environ.get("ADMIN_PASSWORD", "jingui2026"))


def _make_case(**kw):
    return {
        "title": "湿病——麻黄加术汤证",
        "content": "患者张某，男，45岁。淋雨后全身关节疼痛沉重，恶寒发热无汗。",
        "symptoms": "身痛重着、恶寒发热、无汗",
        "diagnosis": "湿病（表湿证）",
        "prescription": "麻黄加术汤",
        "difficulty_level": "初级",
        "teaching_points": "辨病关键：身痛重着+恶寒发热=表湿",
        "correct_answer": "辨病：湿病。定治：麻黄加术汤。",
        **kw,
    }


def _make_text(**kw):
    base = {
        "source_book": "《伤寒论》",
        "chapter": "辨太阳病脉证并治",
        "section": "上",
        "article_number": 1,
        "content": "太阳之为病，脉浮，头项强痛而恶寒。",
    }
    base.update(kw)
    return base


# ==================== 病案 ====================

class TestCases:
    def test_create_requires_admin(self, client):
        assert client.post("/api/cases/", json=_make_case()).status_code == 401

    def test_create_ok(self, client):
        resp = client.post("/api/cases/", json=_make_case(), auth=ADMIN_AUTH)
        assert resp.status_code == 201
        assert resp.json()["title"] == "湿病——麻黄加术汤证"

    def test_create_missing_title(self, client):
        bad = _make_case()
        del bad["title"]
        assert client.post("/api/cases/", json=bad, auth=ADMIN_AUTH).status_code == 422

    def test_list_empty(self, client):
        assert client.get("/api/cases/").json() == []

    def test_list_and_filter(self, client):
        client.post("/api/cases/", json=_make_case(title="湿病案"), auth=ADMIN_AUTH)
        client.post("/api/cases/", json=_make_case(title="胸痹案", difficulty_level="中级"),
                    auth=ADMIN_AUTH)

        assert len(client.get("/api/cases/").json()) == 2
        filtered = client.get("/api/cases/?title=胸痹").json()
        assert len(filtered) == 1
        assert "胸痹" in filtered[0]["title"]

    def test_update_and_delete(self, client):
        case_id = client.post("/api/cases/", json=_make_case(), auth=ADMIN_AUTH).json()["id"]

        assert client.put(f"/api/cases/{case_id}", json={"title": "改"}).status_code == 401
        updated = client.put(f"/api/cases/{case_id}", json={"title": "新标题"}, auth=ADMIN_AUTH)
        assert updated.status_code == 200 and updated.json()["title"] == "新标题"

        assert client.delete(f"/api/cases/{case_id}").status_code == 401
        assert client.delete(f"/api/cases/{case_id}", auth=ADMIN_AUTH).status_code == 204

    def test_batch_delete(self, client):
        assert client.post("/api/cases/batch-delete", json={"ids": [1]}).status_code == 401

        r1 = client.post("/api/cases/", json=_make_case(title="A"), auth=ADMIN_AUTH)
        r2 = client.post("/api/cases/", json=_make_case(title="B"), auth=ADMIN_AUTH)
        ids = [r1.json()["id"], r2.json()["id"]]

        resp = client.post("/api/cases/batch-delete", json={"ids": ids}, auth=ADMIN_AUTH)
        assert resp.json()["success"] is True
        assert client.get("/api/cases/").json() == []


# ==================== 条文 ====================

class TestTexts:
    def test_create_requires_admin(self, client):
        assert client.post("/api/texts/", json=_make_text()).status_code == 401

    def test_create_ok(self, client):
        resp = client.post("/api/texts/", json=_make_text(), auth=ADMIN_AUTH)
        assert resp.status_code == 201
        data = resp.json()
        assert data["content"] == "太阳之为病，脉浮，头项强痛而恶寒。"
        assert data["id"] is not None

    def test_create_missing_content(self, client):
        bad = _make_text()
        del bad["content"]
        assert client.post("/api/texts/", json=bad, auth=ADMIN_AUTH).status_code == 422

    def test_list_empty(self, client):
        assert client.get("/api/texts/").json() == []

    def test_list_and_filters(self, client):
        client.post("/api/texts/", json=_make_text(article_number=1), auth=ADMIN_AUTH)
        client.post("/api/texts/", json=_make_text(article_number=2, source_book="《金匮要略》"),
                    auth=ADMIN_AUTH)
        client.post("/api/texts/", json=_make_text(article_number=180,
                                                   chapter="辨阳明病脉证并治"),
                    auth=ADMIN_AUTH)

        assert len(client.get("/api/texts/").json()) == 3
        by_book = client.get("/api/texts/?source_book=《金匮要略》").json()
        assert len(by_book) == 1 and by_book[0]["source_book"] == "《金匮要略》"
        by_chapter = client.get("/api/texts/?chapter=辨阳明病脉证并治").json()
        assert len(by_chapter) == 1

    def test_pagination_and_sort(self, client):
        for n in (5, 1, 3):
            client.post("/api/texts/", json=_make_text(article_number=n), auth=ADMIN_AUTH)

        paged = client.get("/api/texts/?skip=1&limit=2").json()
        assert len(paged) == 2

        sorted_nums = [t["article_number"] for t in client.get("/api/texts/?sort_by=article_number").json()]
        assert sorted_nums == [1, 3, 5]

    def test_get_update_delete(self, client):
        text_id = client.post("/api/texts/", json=_make_text(), auth=ADMIN_AUTH).json()["id"]

        assert client.get(f"/api/texts/{text_id}").json()["article_number"] == 1
        assert client.get("/api/texts/99999").status_code == 404

        assert client.put(f"/api/texts/{text_id}", json={"content": "改"}).status_code == 401
        updated = client.put(
            f"/api/texts/{text_id}",
            json={"content": "太阳病，发热汗出恶风脉缓者，名为中风。"},
            auth=ADMIN_AUTH,
        )
        assert updated.status_code == 200 and "中风" in updated.json()["content"]

        assert client.delete(f"/api/texts/{text_id}").status_code == 401
        assert client.delete(f"/api/texts/{text_id}", auth=ADMIN_AUTH).status_code == 204
        assert client.get(f"/api/texts/{text_id}").status_code == 404

    def test_batch_delete(self, client):
        assert client.post("/api/texts/batch-delete", json={"ids": [1]}).status_code == 401

        r1 = client.post("/api/texts/", json=_make_text(article_number=1), auth=ADMIN_AUTH)
        r2 = client.post("/api/texts/", json=_make_text(article_number=2), auth=ADMIN_AUTH)
        ids = [r1.json()["id"], r2.json()["id"]]

        resp = client.post("/api/texts/batch-delete", json={"ids": ids}, auth=ADMIN_AUTH)
        assert resp.status_code == 200 and resp.json()["success"] is True
        assert client.get("/api/texts/").json() == []

    def test_chapter_tree_is_public(self, client):
        resp = client.get("/api/texts/chapters")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


# ==================== 文档 ====================

class TestDocuments:
    def test_upload_requires_admin(self, client):
        assert client.post("/api/documents/upload").status_code == 401

    def test_upload_txt_ok(self, client):
        content = "太阳病，头痛发热，汗出恶风者，桂枝汤主之。（1）\n阳明病，胃家实是也。（2）"
        files = {"file": ("test.txt", io.BytesIO(content.encode("utf-8")), "text/plain")}
        resp = client.post("/api/documents/upload", files=files, auth=ADMIN_AUTH)
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_upload_invalid_type(self, client):
        files = {"file": ("test.png", io.BytesIO(b"fake"), "image/png")}
        assert client.post("/api/documents/upload", files=files, auth=ADMIN_AUTH).status_code == 400

    def test_upload_empty_filename(self, client):
        files = {"file": ("", io.BytesIO(b"x"), "text/plain")}
        resp = client.post("/api/documents/upload", files=files, auth=ADMIN_AUTH)
        assert resp.status_code in (400, 422)

    def test_list_is_public(self, client):
        resp = client.get("/api/documents/")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_delete_requires_admin_and_handles_missing(self, client):
        assert client.delete("/api/documents/1").status_code == 401
        assert client.delete("/api/documents/99999", auth=ADMIN_AUTH).status_code == 404

    def test_retry(self, client):
        assert client.post("/api/documents/1/retry").status_code == 401
        assert client.post("/api/documents/99999/retry", auth=ADMIN_AUTH).status_code == 404

# ==================== 分页（P2-3） ====================

class TestPagination:
    """列表接口通过响应头返回总数，响应体保持为数组（向后兼容）。"""

    def test_total_count_header_and_window(self, client):
        for n in (1, 2, 3):
            client.post("/api/texts/", json=_make_text(article_number=n), auth=ADMIN_AUTH)

        resp = client.get("/api/texts/?limit=2")

        assert resp.status_code == 200
        assert isinstance(resp.json(), list), "响应体结构不应被分页改动"
        assert resp.headers["X-Total-Count"] == "3"
        assert resp.headers["X-Skip"] == "0"
        assert resp.headers["X-Limit"] == "2"
        assert len(resp.json()) == 2

    def test_skip_moves_window(self, client):
        for n in (1, 2, 3):
            client.post("/api/texts/", json=_make_text(article_number=n), auth=ADMIN_AUTH)

        first = client.get("/api/texts/?limit=2&skip=0").json()
        second = client.get("/api/texts/?limit=2&skip=2").json()

        assert [t["article_number"] for t in first] == [1, 2]
        assert [t["article_number"] for t in second] == [3]

    def test_empty_result_reports_zero_total(self, client):
        resp = client.get("/api/texts/")

        assert resp.json() == []
        assert resp.headers["X-Total-Count"] == "0"

    def test_total_reflects_filter(self, client):
        client.post("/api/texts/", json=_make_text(article_number=1), auth=ADMIN_AUTH)
        client.post(
            "/api/texts/",
            json=_make_text(article_number=2, source_book="《金匮要略》"),
            auth=ADMIN_AUTH,
        )

        resp = client.get("/api/texts/?source_book=《金匮要略》")

        assert resp.headers["X-Total-Count"] == "1"
        assert len(resp.json()) == 1

    def test_admin_case_list_reports_total(self, client):
        client.post("/api/cases/", json=_make_case(title="A"), auth=ADMIN_AUTH)
        client.post("/api/cases/", json=_make_case(title="B"), auth=ADMIN_AUTH)

        resp = client.get("/api/cases/admin/?limit=1", auth=ADMIN_AUTH)

        assert resp.headers["X-Total-Count"] == "2"
        assert len(resp.json()) == 1
