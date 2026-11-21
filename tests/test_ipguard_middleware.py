"""
ipguard middleware 辅助函数单元测试
"""

from flask import Flask, request

from Module.ipguard.middleware import get_client_ip, is_other_ua, is_whitelisted


def test_get_client_ip_xff_priority(monkeypatch):
    """设置 TRUST_PROXY_HEADERS=1 时 X-Forwarded-For 优先，取第一个 IP"""
    monkeypatch.setenv("TRUST_PROXY_HEADERS", "1")
    app = Flask(__name__)

    with app.test_request_context(
        "/", headers={"X-Forwarded-For": "9.9.9.9, 10.0.0.1"}
    ):
        assert get_client_ip() == "9.9.9.9"


def test_get_client_ip_xff_ignored_without_trust(monkeypatch):
    """未设置 TRUST_PROXY_HEADERS 时 XFF 不可信，回退 remote_addr"""
    monkeypatch.delenv("TRUST_PROXY_HEADERS", raising=False)
    app = Flask(__name__)

    with app.test_request_context(
        "/",
        headers={"X-Forwarded-For": "9.9.9.9, 10.0.0.1"},
        environ_base={"REMOTE_ADDR": "5.5.5.5"},
    ):
        assert get_client_ip() == "5.5.5.5"


def test_get_client_ip_xreal_ip_when_trusted(monkeypatch):
    """TRUST_PROXY_HEADERS=1 且无 XFF 时支持 X-Real-IP"""
    monkeypatch.setenv("TRUST_PROXY_HEADERS", "1")
    app = Flask(__name__)

    with app.test_request_context("/", headers={"X-Real-IP": "6.6.6.6"}):
        assert get_client_ip() == "6.6.6.6"


def test_get_client_ip_fallback_remote_addr(monkeypatch):
    """无 XFF 时回退 remote_addr"""
    monkeypatch.delenv("TRUST_PROXY_HEADERS", raising=False)
    app = Flask(__name__)

    with app.test_request_context("/", environ_base={"REMOTE_ADDR": "5.5.5.5"}):
        assert get_client_ip() == "5.5.5.5"


def test_is_other_ua_normal_browser_false():
    """正常浏览器 UA 不视为 Other"""
    app = Flask(__name__)

    with app.test_request_context(
        "/",
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
        },
    ):
        assert is_other_ua() is False


def test_is_other_ua_unknown_ua_true():
    """未知 UA 视为 Other"""
    app = Flask(__name__)

    with app.test_request_context("/", headers={"User-Agent": "curl/8.0"}):
        assert is_other_ua() is True


def test_is_whitelisted_paths():
    """白名单路径返回 True"""
    app = Flask(__name__)

    checks = {
        "/static/css/app.css": True,
        "/favicon.ico": True,
        "/setup": True,
        "/ipguard/banned": True,
        "/ipguard/rate_limited": True,
        "/": False,
        "/user/login": False,
        "/book/view/1": False,
    }
    for path, expected in checks.items():
        with app.test_request_context(path):
            assert is_whitelisted(path) is expected


UA_CHROME = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def _make_superadmin():
    """创建并登录超级管理员（uid 0-9 且 role=admin）"""
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


def _make_user():
    """创建并登录普通用户"""
    from Module.common import user_utils

    users = {
        "alice": {
            "id": 10,
            "username": "alice",
            "password": "p",
            "role": "user",
            "enabled": True,
            "is_superadmin": False,
        }
    }
    user_utils.save_users(users)


def test_superadmin_exempt_from_all(app, client):
    """超级管理员访问任何页面均不被限制"""
    _make_superadmin()
    with client.session_transaction() as sess:
        sess["user_id"] = 0
        sess["username"] = "admin"
        sess["role"] = "admin"
        sess["verified"] = True
    for _ in range(30):
        resp = client.get("/")
    assert resp.status_code == 200


def test_login_page_rate_limited(app, client):
    """未登录高频访问 /user/login 触发封禁返回 429"""
    for _ in range(6):
        resp = client.get("/user/login", headers={"User-Agent": UA_CHROME})
    assert resp.status_code == 429
    assert "访问受限" in resp.get_data(as_text=True)


def test_normal_user_access_not_blocked(app, client):
    """普通用户正常低频访问不受限"""
    _make_user()
    with client.session_transaction() as sess:
        sess["user_id"] = 10
        sess["username"] = "alice"
        sess["role"] = "user"
        sess["verified"] = True
    for _ in range(5):
        resp = client.get("/", headers={"User-Agent": UA_CHROME})
    assert resp.status_code == 200


def test_normal_user_single_path_over_limit(app, client):
    """普通用户同一路径1分钟超过10次触发限速提示"""
    from Module.common import user_utils
    from Module.ipguard import rate_limiter, ban_manager

    rate_limiter.reset_state()
    ban_manager.reset_state()
    _make_user()
    with client.session_transaction() as sess:
        sess["user_id"] = 10
        sess["username"] = "alice"
        sess["role"] = "user"
        sess["verified"] = True
    last = None
    for _ in range(12):
        last = client.get("/", headers={"User-Agent": UA_CHROME})
    assert last.status_code == 429
    assert "请稍后再试" in last.get_data(as_text=True)


def test_static_files_not_counted(app, client):
    """静态文件不触发第一防线UA限制"""
    from Module.ipguard import rate_limiter

    rate_limiter.reset_state()
    for _ in range(30):
        resp = client.get("/static/style.css", headers={"User-Agent": "curl/8.0"})
    assert resp.status_code == 404  # 未限制，且静态文件不存在返回404而非被拦截


def test_line2_second_trigger_ban_2min(app, client):
    """第二防线第2次触发（10 分钟窗口内再次超限）返回封禁页（访问受限）且封禁落库"""
    import time

    from Module.ipguard import rate_limiter, ban_manager

    rate_limiter.reset_state()
    ban_manager.reset_state()
    _make_user()
    with client.session_transaction() as sess:
        sess["user_id"] = 10
        sess["username"] = "alice"
        sess["role"] = "user"
        sess["verified"] = True

    ip = "127.0.0.1"
    # 第1次触发：限速提示
    for _ in range(12):
        resp = client.get("/", headers={"User-Agent": UA_CHROME})
    assert resp.status_code == 429
    assert "请稍后再试" in resp.get_data(as_text=True)

    # 推进窗口：退出限速期，保留触发计数=1
    with rate_limiter._line2_lock:
        rate_limiter._line2_state[ip] = {
            "trigger_count": 1,
            "last_trigger": time.time(),
            "expires": 0,
        }

    # 第2次触发：封禁 2 分钟
    resp = client.get("/", headers={"User-Agent": UA_CHROME})
    assert resp.status_code == 429
    assert "访问受限" in resp.get_data(as_text=True)
    banned, remaining = ban_manager.is_ip_banned(ip)
    assert banned is True and remaining is not None and remaining <= 120


def test_line2_third_trigger_permanent_ban_and_disable_user(app, client):
    """第二防线第3次触发：永久封禁并禁用用户账户"""
    import time

    from Module.common import user_utils
    from Module.ipguard import rate_limiter, ban_manager

    rate_limiter.reset_state()
    ban_manager.reset_state()
    _make_user()
    with client.session_transaction() as sess:
        sess["user_id"] = 10
        sess["username"] = "alice"
        sess["role"] = "user"
        sess["verified"] = True

    ip = "127.0.0.1"
    # 第1次触发：限速提示
    for _ in range(12):
        client.get("/", headers={"User-Agent": UA_CHROME})

    # 第2次触发：封禁 2 分钟
    with rate_limiter._line2_lock:
        rate_limiter._line2_state[ip] = {
            "trigger_count": 1,
            "last_trigger": time.time(),
            "expires": 0,
        }
    resp = client.get("/", headers={"User-Agent": UA_CHROME})
    assert resp.status_code == 429
    assert "访问受限" in resp.get_data(as_text=True)

    # 解除 2 分钟封禁，为第3次触发让路（缓存与库记录一并清除）
    ban_manager.unban(ip)
    with rate_limiter._line2_lock:
        rate_limiter._line2_state[ip] = {
            "trigger_count": 2,
            "last_trigger": time.time(),
            "expires": 0,
        }

    # 第3次触发：永久封禁 + 禁用账户
    resp = client.get("/", headers={"User-Agent": UA_CHROME})
    assert resp.status_code == 429
    assert "访问受限" in resp.get_data(as_text=True)
    banned, remaining = ban_manager.is_ip_banned(ip)
    assert banned is True
    assert remaining is None  # 永久封禁
    users = user_utils.load_users()
    assert users["alice"]["enabled"] is False
