"""
综合集成测试：应用启动、蓝图注册、端点冒烟、认证流程
"""

import importlib
import sys
from pathlib import Path

import pytest
from flask import session

from Module.common import db_utils, user_utils


# ============================================================================
# 辅助函数
# ============================================================================


def _create_user_and_login(
    client, app, username="alice", role="user", user_id=1, enabled=True, verified=True
):
    """创建用户并注入登录态"""
    user_utils.save_users(
        {
            username: {
                "id": user_id,
                "username": username,
                "password": "pass123",
                "role": role,
                "enabled": enabled,
            },
        }
    )
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["username"] = username
        sess["role"] = role
        sess["verified"] = verified


def _create_admin_and_login(client, app, username="admin", user_id=0, verified=True):
    """创建超级管理员并注入登录态"""
    _create_user_and_login(
        client,
        app,
        username=username,
        role="admin",
        user_id=user_id,
        verified=verified,
    )


# ============================================================================
# 1. 应用启动与蓝图注册
# ============================================================================


class TestAppStartup:
    """测试应用启动和蓝图注册"""

    def test_app_creates_successfully(self, app):
        """应用工厂函数可正常创建应用"""
        assert app is not None
        assert app.config["TESTING"] is True

    def test_all_blueprints_registered(self, app):
        """所有蓝图已注册"""
        blueprint_names = set(app.blueprints.keys())
        expected = {
            "index",
            "books",
            "user",
            "admin",
            "admin_activity",
            "admin_users",
            "admin_config",
            "admin_mounted",
            "admin_setting",
            "admin_ip",
            "userfix",
            "userfix_admin",
            "gallery",
            "gallery_favorites",
            "gallery_preferences",
            "setup",
            "ipguard",
        }
        missing = expected - blueprint_names
        assert not missing, f"Missing blueprints: {missing}"

    def test_database_initialized(self, app):
        """数据库初始化后关键表存在"""
        with app.app_context():
            tables = db_utils.query("SELECT name FROM sqlite_master WHERE type='table'")
            names = {t["name"] for t in tables}
            assert {
                "users",
                "books",
                "activity_log",
                "active_sessions",
                "favorites",
            } <= names

    def test_secret_key_set(self, app):
        """SECRET_KEY 已配置"""
        assert app.config.get("SECRET_KEY")

    def test_session_cookie_config(self, app):
        """Session cookie 安全属性已配置"""
        assert app.config.get("SESSION_COOKIE_HTTPONLY") is True
        assert app.config.get("SESSION_COOKIE_SAMESITE") == "Lax"


# ============================================================================
# 2. 模块导入检查
# ============================================================================


class TestImports:
    """验证所有模块可正常导入，无循环导入"""

    def test_import_common_modules(self):
        """公共模块可正常导入"""
        from Module.common import auth_utils
        from Module.common import config_utils
        from Module.common import db_utils
        from Module.common import file_utils
        from Module.common import pagination
        from Module.common import paths
        from Module.common import response
        from Module.common import security
        from Module.common import user_utils

    def test_import_core_services(self):
        """核心服务可正常导入"""
        from Module.core import admin_service
        from Module.core import books_service
        from Module.core import gallery_service
        from Module.core import user_service
        from Module.core import userfix_service

    def test_import_module_blueprints(self):
        """各模块蓝图可正常导入"""
        from Module.index import index_bp
        from Module.books import books_bp
        from Module.user import user_bp
        from Module.admin import (
            admin_bp,
            admin_activity_bp,
            admin_users_bp,
            admin_config_bp,
            admin_mounted_bp,
        )
        from Module.gallery import (
            gallery_bp,
            gallery_favorites_bp,
            gallery_preferences_bp,
        )
        from Module.userfix import userfix_bp, userfix_admin_bp


# ============================================================================
# 3. 公开端点（无需认证）
# ============================================================================


class TestPublicEndpoints:
    """测试公开可访问的端点"""

    def test_login_page_returns_200(self, client):
        """登录页可公开访问"""
        resp = client.get("/user/login")
        assert resp.status_code == 200
        assert "登录" in resp.get_data(as_text=True)

    def test_index_unauthenticated_redirects(self, client):
        """未登录访问首页被重定向到登录页"""
        resp = client.get("/")
        assert resp.status_code == 302
        assert resp.location.endswith("/login")

    def test_books_unauthenticated_redirects(self, client):
        """未登录访问书籍页被重定向"""
        resp = client.get("/book/")
        assert resp.status_code == 302
        assert resp.location.endswith("/login")

    def test_gallery_unauthenticated_redirects(self, client):
        """未登录访问画廊页被重定向"""
        resp = client.get("/gallery/")
        assert resp.status_code == 302
        assert resp.location.endswith("/login")

    def test_unknown_route_unauthenticated_redirects(self, client):
        """未登录访问未知路由被重定向到登录"""
        resp = client.get("/nonexistent")
        assert resp.status_code == 302
        assert resp.location.endswith("/login")


# ============================================================================
# 4. 已认证用户的受保护端点
# ============================================================================


class TestAuthenticatedEndpoints:
    """测试需要登录的端点"""

    def test_index_returns_200(self, client, app):
        """已登录用户可访问首页"""
        _create_user_and_login(client, app)
        resp = client.get("/")
        assert resp.status_code == 200

    def test_books_index_returns_200(self, client, app):
        """已登录用户可访问书籍页"""
        _create_user_and_login(client, app)
        resp = client.get("/book/")
        assert resp.status_code == 200

    def test_books_search_returns_200(self, client, app):
        """已登录用户可搜索书籍"""
        _create_user_and_login(client, app)
        resp = client.get("/book/search?q=test")
        assert resp.status_code == 200

    def test_gallery_index_returns_200(self, client, app):
        """已登录用户可访问画廊"""
        _create_user_and_login(client, app)
        resp = client.get("/gallery/")
        assert resp.status_code == 200

    def test_user_profile_returns_200(self, client, app):
        """已登录用户可访问个人资料"""
        _create_user_and_login(client, app)
        resp = client.get("/user/profile")
        assert resp.status_code == 200

    def test_404_returns_json(self, client, app):
        """已登录用户访问不存在路由返回 404"""
        _create_user_and_login(client, app)
        resp = client.get("/nonexistent")
        assert resp.status_code == 404

    def test_disabled_user_blocked(self, client, app):
        """被禁用用户访问受保护路由被重定向"""
        _create_user_and_login(client, app, enabled=False)
        resp = client.get("/")
        assert resp.status_code == 302
        assert resp.location.endswith("/login")


# ============================================================================
# 5. 管理员端点
# ============================================================================


class TestAdminEndpoints:
    """测试管理后台端点（需要超级管理员权限）"""

    def test_admin_dashboard_requires_admin(self, client, app):
        """普通用户无法访问管理后台"""
        _create_user_and_login(client, app, role="user")
        resp = client.get("/admin/")
        assert resp.status_code == 302
        assert resp.location.endswith("/login")

    def test_admin_dashboard_accessible(self, client, app):
        """超级管理员可访问仪表盘"""
        _create_admin_and_login(client, app)
        resp = client.get("/admin/")
        assert resp.status_code == 200

    def test_admin_activity_accessible(self, client, app):
        """超级管理员可访问活动日志"""
        _create_admin_and_login(client, app)
        resp = client.get("/admin/activity")
        assert resp.status_code == 200

    def test_admin_activity_api_accessible(self, client, app):
        """超级管理员可访问活动日志 API"""
        _create_admin_and_login(client, app)
        resp = client.get("/admin/activity/api")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True

    def test_admin_config_accessible(self, client, app):
        """超级管理员可访问配置页"""
        _create_admin_and_login(client, app)
        resp = client.get("/admin/config")
        assert resp.status_code == 200

    def test_admin_config_api_accessible(self, client, app):
        """超级管理员可访问配置 API"""
        _create_admin_and_login(client, app)
        resp = client.get("/admin/config/api")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True

    def test_admin_unverified_redirects_to_verify(self, client, app):
        """未验证的管理员被重定向到验证页"""
        _create_admin_and_login(client, app, verified=False)
        resp = client.get("/admin/")
        assert resp.status_code == 302
        assert resp.location.endswith("/verify")

    def test_non_superadmin_blocked(self, client, app):
        """uid > 9 的 admin 用户无法访问管理后台"""
        _create_admin_and_login(client, app, user_id=10)
        resp = client.get("/admin/")
        assert resp.status_code == 302


# ============================================================================
# 6. API 端点
# ============================================================================


class TestAPIEndpoints:
    """测试 API 端点"""

    def test_gallery_random_images(self, client, app):
        """画廊随机图片 API"""
        _create_user_and_login(client, app)
        resp = client.get("/gallery/api/random-images")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert "images" in data

    def test_gallery_random_images_with_count(self, client, app):
        """画廊随机图片 API 指定数量"""
        _create_user_and_login(client, app)
        resp = client.get("/gallery/api/random-images?count=5")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True

    def test_gallery_search(self, client, app):
        """画廊搜索 API"""
        _create_user_and_login(client, app)
        resp = client.get("/gallery/api/search?q=test")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert "results" in data
        assert "folders" in data["results"]
        assert "images" in data["results"]

    def test_gallery_search_empty_query(self, client, app):
        """画廊搜索空查询返回空列表"""
        _create_user_and_login(client, app)
        resp = client.get("/gallery/api/search?q=")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["results"]["folders"] == []
        assert data["results"]["images"] == []

    def test_books_search_api(self, client, app):
        """书籍搜索返回 200"""
        _create_user_and_login(client, app)
        resp = client.get("/book/search?q=test")
        assert resp.status_code == 200

    def test_admin_activity_api(self, client, app):
        """管理后台活动日志 API"""
        _create_admin_and_login(client, app)
        resp = client.get("/admin/activity/api")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert "activities" in data
        assert "total" in data

    def test_admin_config_api(self, client, app):
        """管理后台配置 API"""
        _create_admin_and_login(client, app)
        resp = client.get("/admin/config/api")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert "config" in data


# ============================================================================
# 7. 认证流程
# ============================================================================


class TestAuthFlow:
    """测试完整的认证流程"""

    def test_login_page_loads(self, client):
        """登录页面可加载"""
        resp = client.get("/user/login")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert "登录" in html

    def test_unauthenticated_access_redirects(self, client):
        """未认证访问受保护页面被重定向到登录"""
        resp = client.get("/")
        assert resp.status_code == 302
        assert "/login" in resp.location

    def test_session_state_after_login(self, client, app):
        """登录后 session 状态正确"""
        _create_user_and_login(client, app, username="bob")
        with client.session_transaction() as sess:
            assert sess.get("username") == "bob"
            assert sess.get("role") == "user"
            assert sess.get("verified") is True

    def test_admin_session_state(self, client, app):
        """管理员登录后 session 状态正确"""
        _create_admin_and_login(client, app, username="superadmin")
        with client.session_transaction() as sess:
            assert sess.get("username") == "superadmin"
            assert sess.get("role") == "admin"
            assert sess.get("verified") is True


# ============================================================================
# 8. 错误处理
# ============================================================================


class TestErrorHandling:
    """测试错误处理"""

    def test_404_api_returns_json(self, client, app):
        """API 请求 404 保持 JSON（ADR-0010）"""
        _create_user_and_login(client, app)
        resp = client.get("/nonexistent", headers={"Accept": "application/json"})
        assert resp.status_code == 404
        data = resp.get_json()
        assert data["code"] == 404
        assert data["error"] == "Not found"

    def test_404_page_returns_html_error_page(self, client, app):
        """页面导航 404 返回中文错误页，不再暴露裸 JSON（ADR-0010）"""
        _create_user_and_login(client, app)
        resp = client.get("/nonexistent", headers={"Accept": "text/html"})
        assert resp.status_code == 404
        assert resp.mimetype == "text/html"
        assert "页面不存在" in resp.get_data(as_text=True)

    def test_admin_endpoint_without_auth_redirects(self, client):
        """管理后台端点未认证时重定向"""
        resp = client.get("/admin/")
        assert resp.status_code == 302
        assert "/login" in resp.location


# ============================================================================
# 9. 安全检查
# ============================================================================


class TestSecurity:
    """测试安全相关功能"""

    def test_security_headers_present(self, client, app):
        """响应包含安全头"""
        _create_user_and_login(client, app)
        resp = client.get("/")
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"
        assert resp.headers.get("X-Frame-Options") == "SAMEORIGIN"
        assert resp.headers.get("X-XSS-Protection") == "1; mode=block"
        assert "Content-Security-Policy" in resp.headers

    def test_csrf_post_without_token_blocked(self, client, app):
        """POST 请求无 CSRF token 被拒绝"""
        _create_user_and_login(client, app)
        resp = client.post("/admin/config/update", json={"test": "value"})
        assert resp.status_code == 403

    def test_login_whitelist_accessible(self, client):
        """白名单路径不需要认证"""
        resp = client.get("/user/login")
        assert resp.status_code == 200
