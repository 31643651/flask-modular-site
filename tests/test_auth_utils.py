"""
auth_utils 认证检查与认证装饰器 单元测试
"""

from Module.common import auth_utils
from Module.common import user_utils


def _save(**overrides):
    """在测试库写入一个启用用户（普通用户或管理员）"""
    user = {
        "id": 1,
        "username": "alice",
        "password": "p",
        "role": "user",
        "enabled": True,
    }
    user.update(overrides)
    user_utils.save_users({user["username"]: user})


def _set_session(client, username="alice", role="user", verified=True):
    """通过 session_transaction 直接写入登录态 cookie，仅供本测试客户端消费"""
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["username"] = username
        sess["role"] = role
        sess["verified"] = verified


def test_unauthenticated_protected_redirects_to_login(client):
    """未登录访问受保护路径被 before_request 重定向到登录"""
    resp = client.get("/")
    assert resp.status_code == 302
    assert resp.location.endswith("/login")


def test_whitelist_login_page_public(client):
    """白名单登录页无需登录即可访问"""
    resp = client.get("/user/login")
    assert resp.status_code == 200


def test_logged_in_user_allowed(client):
    """已启用普通用户登录后可访问受保护路径（check_auth 通过）"""
    _save()
    _set_session(client)
    resp = client.get("/")
    assert resp.status_code == 200


def test_disabled_user_blocked(client):
    """被禁用用户登录态被拒绝访问"""
    _save(enabled=False)
    _set_session(client)
    resp = client.get("/")
    assert resp.status_code == 302
    assert resp.location.endswith("/login")


def test_admin_unverified_redirects_to_verify(client):
    """管理员未二次验证时被重定向到验证页"""
    _save(role="admin", username="admin")
    _set_session(client, username="admin", role="admin", verified=False)
    resp = client.get("/")
    assert resp.status_code == 302
    assert resp.location.endswith("/verify")


def test_require_auth_not_logged_returns_redirect(app, client):
    """require_auth 未登录时返回 302 指向登录"""
    with app.test_request_context("/required"):
        result = auth_utils.require_auth()
        assert result is not None
        assert result.status_code == 302
        assert result.location.endswith("/user/login")


def test_check_auth_whitelist_login_public(app):
    """未登录访问白名单路径 /user/login 时 check_auth 放行（回归：Windows 下不得因路径规范化反斜杠而失效）"""
    with app.test_request_context("/user/login"):
        assert auth_utils.check_auth() is True


def test_check_auth_whitelist_prefix_public(app):
    """未登录访问白名单前缀路径 /static/xxx 时 check_auth 放行"""
    with app.test_request_context("/static/css/site.css"):
        assert auth_utils.check_auth() is True


def test_check_auth_non_whitelist_requires_login(app):
    """未登录访问非白名单路径时 check_auth 拒绝"""
    with app.test_request_context("/book"):
        assert auth_utils.check_auth() is False
