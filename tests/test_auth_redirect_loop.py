"""
302 循环治理测试（ADR-0004）

- 角色判定单一权威源：/user/verify 以 DB 角色为准，与 /user/login 不再互跳成环
- 2 秒窗口内第 4 个 302 → 508 Loop Detected（服务端硬熔断）
"""

# 浏览器 UA：避开 ipguard 第一防线 UA=Other 桶，防止 429 干扰断言
CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def _save_user(**overrides):
    """写入一个启用用户（默认普通用户 alice）"""
    from Module.common import user_utils

    user = {
        "id": 1,
        "username": "alice",
        "password": "p",
        "role": "user",
        "enabled": True,
    }
    user.update(overrides)
    user_utils.save_users({user["username"]: user})


def _set_session(client, username="alice", role="user", verified=False):
    """直接写登录态 session（session.role 刻意允许与 DB 不一致，用于模拟陈旧快照）"""
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["username"] = username
        sess["role"] = role
        sess["verified"] = verified


def test_verify_renders_for_db_admin_with_stale_session_role(client):
    """外部提权后 session.role 仍是 user：/user/verify 必须渲染，而不是跳回 /user/login 成环"""
    _save_user(role="admin")
    _set_session(client, role="user", verified=False)
    resp = client.get("/user/verify")
    assert resp.status_code == 200  # 红灯：当前按 session.role 判非 admin → 302 回登录 → 死循环


def test_verify_redirects_login_for_demoted_session_admin(client):
    """DB 已降级为普通用户但 session.role 残留 admin：/user/verify 不得渲染，跳回登录"""
    _save_user(role="user")
    _set_session(client, role="admin", verified=False)
    resp = client.get("/user/verify")
    assert resp.status_code == 302  # 红灯：当前信 session.role → 渲染 200
    assert resp.location.endswith("/user/login")


def test_verify_redirects_login_for_disabled_admin(client):
    """被禁用的管理员不得停留在验证页，跳回登录"""
    _save_user(username="admin", role="admin", enabled=False)
    _set_session(client, username="admin", role="admin", verified=False)
    resp = client.get("/user/verify")
    assert resp.status_code == 302  # 红灯：当前不查 enabled → 渲染 200
    assert resp.location.endswith("/user/login")


def test_circuit_breaker_4th_302_within_2s_returns_508(client):
    """2 秒窗口内第 4 个 302 → 508 Loop Detected，且不带 Location"""
    for _ in range(3):
        resp = client.get("/", headers={"User-Agent": CHROME_UA})
        assert resp.status_code == 302
    resp4 = client.get("/", headers={"User-Agent": CHROME_UA})
    assert resp4.status_code == 508  # 红灯：当前第 4 个仍是 302（无熔断）
    assert "Location" not in resp4.headers


def test_circuit_window_resets_on_non_redirect(client):
    """非 302 响应清零窗口：3 次 302 + 1 次 200 后，再 2 次 302 不得熔断（回归守卫）"""
    for _ in range(3):
        resp = client.get("/", headers={"User-Agent": CHROME_UA})
        assert resp.status_code == 302
    resp = client.get("/user/login", headers={"User-Agent": CHROME_UA})
    assert resp.status_code == 200
    for _ in range(2):
        resp = client.get("/", headers={"User-Agent": CHROME_UA})
        assert resp.status_code == 302
