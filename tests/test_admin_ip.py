"""
admin /admin/ip 封禁管理测试
"""


def _seed_ban(ip="1.2.3.4"):
    from Module.ipguard import ban_manager

    ban_manager.execute_progressive_ban(ip, "line1_login")


def _login_superadmin(client):
    from Module.common import user_utils

    users = {
        "admin": {
            "id": 0,
            "username": "admin",
            "password": "p",
            "role": "admin",
            "enabled": True,
            "is_superadmin": True,
        }
    }
    user_utils.save_users(users)
    with client.session_transaction() as sess:
        sess["user_id"] = 0
        sess["username"] = "admin"
        sess["role"] = "admin"
        sess["verified"] = True
        sess["csrf_token"] = "test-csrf-token"


def _csrf_headers():
    return {"X-CSRF-Token": "test-csrf-token"}


def test_admin_ip_page_requires_superadmin(app, client):
    """未登录访问 /admin/ip 重定向到登录"""
    resp = client.get("/admin/ip")
    assert resp.status_code == 302
    assert "login" in resp.location


def test_admin_ip_page_shows_bans(app, client):
    """超级管理员可查看封禁列表"""
    from Module.ipguard.ban_manager import load_ban_cache

    _seed_ban()
    load_ban_cache()
    _login_superadmin(client)
    resp = client.get("/admin/ip")
    assert resp.status_code == 200
    data = resp.get_data(as_text=True)
    assert "1.2.3.4" in data


def test_admin_ip_api_returns_bans(app, client):
    """API 返回最近封禁记录"""
    from Module.ipguard.ban_manager import load_ban_cache

    _seed_ban()
    load_ban_cache()
    _login_superadmin(client)
    resp = client.get("/admin/ip/api/bans")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["success"] is True
    assert any(b["ip"] == "1.2.3.4" for b in payload["bans"])


def test_admin_ip_unban(app, client):
    """管理员解除封禁后不再封禁"""
    from Module.ipguard.ban_manager import load_ban_cache

    _seed_ban()
    load_ban_cache()
    _login_superadmin(client)
    resp = client.post(
        "/admin/ip/unban", json={"ip": "1.2.3.4"}, headers=_csrf_headers()
    )
    assert resp.status_code == 200
    assert resp.get_json()["success"] is True
    from Module.ipguard import ban_manager

    banned, _ = ban_manager.is_ip_banned("1.2.3.4")
    assert banned is False


def test_admin_ip_unban_config_jsonsafe(app, client):
    """解除封禁请求缺少 IP 时返回错误"""
    _login_superadmin(client)
    resp = client.post("/admin/ip/unban", json={}, headers=_csrf_headers())
    assert resp.status_code == 200
    assert resp.get_json()["success"] is False
