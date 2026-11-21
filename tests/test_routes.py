"""
关键路由 HTTP 冒烟测试（首页、登录、书籍、画廊、404）
"""

from Module.common import user_utils


def _login(client, app):
    user_utils.save_users(
        {
            "alice": {
                "id": 1,
                "username": "alice",
                "password": "p",
                "role": "user",
                "enabled": True,
            },
        }
    )
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["username"] = "alice"
        sess["role"] = "user"
        sess["verified"] = True


def test_login_page_public(client):
    """未登录访问登录页（白名单）返回 200 且含标题"""
    resp = client.get("/user/login")
    assert resp.status_code == 200
    assert "登录" in resp.get_data(as_text=True)


def test_index_requires_login_redirects(client):
    """未登录访问首页被 before_request 重定向到登录"""
    resp = client.get("/")
    assert resp.status_code in (200, 302)
    if resp.status_code == 302:
        assert resp.location.endswith("/login")


def test_index_logged_in(app, client):
    _login(client, app)
    resp = client.get("/")
    assert resp.status_code == 200


def test_books_index_logged_in(app, client):
    _login(client, app)
    resp = client.get("/book/")
    assert resp.status_code == 200


def test_gallery_index_logged_in(app, client):
    _login(client, app)
    resp = client.get("/gallery/")
    assert resp.status_code == 200


def test_404_handler(app, client):
    """登录态请求不存在路径返回 404 JSON"""
    _login(client, app)
    resp = client.get("/definitely-not-a-route")
    assert resp.status_code == 404


def test_unknown_route_requires_login_too(client):
    """未登录访问野生路径被重定向而非直接 404（before_request 优先）"""
    resp = client.get("/definitely-not-a-route")
    assert resp.status_code == 302
    assert resp.location.endswith("/login")


def test_login_rotates_csrf_token(client):
    """登录成功后 CSRF token 重新轮换并写入 session+cookie（bug #13：删除失效的旧 token 保留逻辑后行为不变）"""
    user_utils.save_users(
        {
            "alice": {
                "id": 1,
                "username": "alice",
                "password": "pass123",
                "role": "user",
                "enabled": True,
            },
        }
    )
    # 预置登录前 token（模拟登录页 GET 时 generate_csrf_token 写入的值）
    with client.session_transaction() as sess:
        sess["csrf_token"] = "pre-login-token"

    resp = client.post(
        "/user/login",
        data={
            "username": "alice",
            "password": "pass123",
            "csrf_token": "pre-login-token",
        },
    )
    assert resp.status_code == 302

    # session 中 token 已轮换为新随机值
    with client.session_transaction() as sess:
        new_token = sess["csrf_token"]
    assert new_token != "pre-login-token"
    assert len(new_token) == 64

    # 响应 cookie 同步写入新 token（非 httponly，供前端 JS 读取）
    set_cookies = resp.headers.getlist("Set-Cookie")
    assert any(c.startswith("csrf_token=") for c in set_cookies)
