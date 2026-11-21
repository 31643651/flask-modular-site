"""
统一错误页测试（ADR-0010）

- 页面导航（GET + Accept 含 text/html + 非 /api/ 路径）→ HTML 中文错误页（404/403/500）
- API 请求（/api/ 路径，或 Accept 不含 html）→ JSON {"error", "code"}（404/500 文案与现状一致）
- 错误页：纯提示（无 button）、暗夜模式适配、不泄露技术细节
"""

import pytest
from flask import abort

from Module.common import user_utils

HTML_ACCEPT = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
}
JSON_ACCEPT = {"Accept": "application/json"}


def _login(client):
    user_utils.save_users({"bob": {"id": 1001, "username": "bob", "password": "p",
                                   "role": "user", "enabled": True}})
    with client.session_transaction() as sess:
        sess["user_id"] = 1001
        sess["username"] = "bob"
        sess["role"] = "user"
        sess["verified"] = True


@pytest.fixture
def err_routes(app):
    """注册 403/500 触发路由（每个测试独立 app 实例）"""
    app.add_url_rule("/__err403", "err403_test", lambda: abort(403))
    app.add_url_rule("/__err500", "err500_test", lambda: abort(500))
    return app


class TestNotFoundBranching:
    def test_page_returns_html_error_page(self, client, app):
        """浏览器导航 404 → HTML 错误页（不再暴露裸 JSON）"""
        _login(client)
        resp = client.get("/definitely-not-here", headers=HTML_ACCEPT)
        assert resp.status_code == 404
        assert resp.mimetype == "text/html"
        body = resp.get_data(as_text=True)
        assert "页面不存在" in body
        assert "404" in body

    def test_api_path_returns_json(self, client, app):
        """API 路径 404 → 保持 JSON 契约"""
        _login(client)
        resp = client.get("/api/definitely-not-here", headers=JSON_ACCEPT)
        assert resp.status_code == 404
        assert resp.get_json() == {"error": "Not found", "code": 404}

    def test_api_path_wins_over_html_accept(self, client, app):
        """/api/ 路径即使 Accept 带 text/html 也返回 JSON（防 fetch 解析崩）"""
        _login(client)
        resp = client.get("/api/definitely-not-here", headers=HTML_ACCEPT)
        assert resp.get_json() == {"error": "Not found", "code": 404}

    def test_plain_client_without_accept_returns_json(self, client, app):
        """无 Accept 头（脚本/测试客户端）→ JSON，保持既有口径"""
        _login(client)
        resp = client.get("/definitely-not-here")
        assert resp.get_json() == {"error": "Not found", "code": 404}


class TestForbiddenBranching:
    def test_page_returns_html_error_page(self, client, err_routes):
        _login(client)
        resp = client.get("/__err403", headers=HTML_ACCEPT)
        assert resp.status_code == 403
        assert resp.mimetype == "text/html"
        body = resp.get_data(as_text=True)
        assert "访问被拒绝" in body
        assert "403" in body

    def test_api_returns_json(self, client, err_routes):
        _login(client)
        resp = client.get("/__err403", headers=JSON_ACCEPT)
        assert resp.status_code == 403
        assert resp.get_json() == {"error": "Forbidden", "code": 403}


class TestServerErrorBranching:
    def test_page_returns_html_error_page(self, client, err_routes):
        _login(client)
        resp = client.get("/__err500", headers=HTML_ACCEPT)
        assert resp.status_code == 500
        assert resp.mimetype == "text/html"
        body = resp.get_data(as_text=True)
        assert "服务器出错了" in body
        assert "500" in body

    def test_api_returns_json(self, client, err_routes):
        _login(client)
        resp = client.get("/__err500", headers=JSON_ACCEPT)
        assert resp.status_code == 500
        assert resp.get_json() == {"error": "Internal server error", "code": 500}


class TestErrorTemplate:
    def test_pure_hint_no_buttons(self, client, app):
        """纯提示：无按钮元素（用户明确要求）"""
        _login(client)
        body = client.get("/nope-404", headers=HTML_ACCEPT).get_data(as_text=True)
        assert "<button" not in body

    def test_dark_mode_cookie_adaptation(self, client, app):
        """适配暗夜模式（darkMode cookie）"""
        _login(client)
        body = client.get("/nope-404", headers=HTML_ACCEPT).get_data(as_text=True)
        assert "darkMode" in body
        assert "dark-mode" in body

    def test_no_technical_leakage(self, client, app):
        """不泄露请求路径 / 异常 / 服务器路径等技术细节"""
        _login(client)
        body = client.get("/nope-404", headers=HTML_ACCEPT).get_data(as_text=True)
        assert "Traceback" not in body
        assert "nope-404" not in body
        assert app.root_path not in body

    def test_responsive_viewport(self, client, app):
        _login(client)
        body = client.get("/nope-404", headers=HTML_ACCEPT).get_data(as_text=True)
        assert 'name="viewport"' in body
