"""
Initial setup route tests.

Tests the setup wizard step 1 (create admin account) and step 2 (server name).
"""

import os
import pytest
from Module.common.paths import CONFIG_FILE, JSON_DIR


@pytest.fixture
def setup_app(app):
    """Create a test app for setup routes in first-run mode.

    Renames the real config.json to .bak so CONFIG_FILE.exists() returns False,
    then restores it after the test.
    """
    config_existed = CONFIG_FILE.exists()
    if config_existed:
        os.rename(str(CONFIG_FILE), str(CONFIG_FILE) + ".bak")

    yield app

    if os.path.exists(str(CONFIG_FILE)):
        os.remove(str(CONFIG_FILE))
    if config_existed and os.path.exists(str(CONFIG_FILE) + ".bak"):
        os.rename(str(CONFIG_FILE) + ".bak", str(CONFIG_FILE))


@pytest.fixture
def setup_client(setup_app):
    """Test client for setup routes with auth/CSRF bypassed.

    Temporarily removes existing auth_check and check_csrf before_request
    handlers so they don't interfere with the setup routes.
    """
    before_funcs = setup_app.before_request_funcs.get(None, [])
    original_funcs = list(before_funcs)
    setup_app.before_request_funcs[None] = [
        f
        for f in before_funcs
        if getattr(f, "__name__", "") not in ("authentication_check", "check_csrf")
    ]

    yield setup_app.test_client()

    setup_app.before_request_funcs[None] = original_funcs


class TestSetupStep1:
    """Test initial setup step 1: create admin account."""

    def test_get_shows_step1_form(self, setup_client):
        """GET /setup/ shows step 1 form with password fields."""
        resp = setup_client.get("/setup/")
        assert resp.status_code == 200
        html = resp.data.decode()
        assert "创建管理员账户" in html
        assert 'name="step" value="1"' in html
        assert 'name="password"' in html
        assert 'name="confirm_password"' in html
        assert 'name="admin_verify_enabled"' in html
        assert "启用管理员动态验证码" in html

    def test_post_mismatched_passwords_shows_error(self, setup_client):
        """POST with mismatched passwords shows error message."""
        resp = setup_client.post(
            "/setup/",
            data={
                "step": "1",
                "password": "pass1",
                "confirm_password": "pass2",
                "admin_verify_enabled": "on",
            },
        )
        assert resp.status_code == 200
        html = resp.data.decode()
        assert "两次输入的密码不一致" in html
        assert 'name="step" value="1"' in html

    def test_post_matching_passwords_shows_step2(self, setup_client):
        """POST with matching passwords transitions to step 2."""
        resp = setup_client.post(
            "/setup/",
            data={
                "step": "1",
                "password": "admin123",
                "confirm_password": "admin123",
                "admin_verify_enabled": "on",
            },
        )
        assert resp.status_code == 200
        html = resp.data.decode()
        assert "设置服务器名称" in html
        assert 'name="step" value="2"' in html

    def test_session_stores_password(self, setup_client):
        """Step 1 stores password and admin_verify in session."""
        setup_client.post(
            "/setup/",
            data={
                "step": "1",
                "password": "admin123",
                "confirm_password": "admin123",
                "admin_verify_enabled": "on",
            },
        )
        with setup_client.session_transaction() as sess:
            assert sess.get("setup_admin_verify") is True

    def test_session_stores_hash_not_plaintext(self, setup_client):
        """Step 1 后 session 中 setup_password ≠ 明文，且为可用明文校验的哈希（I2）。"""
        from werkzeug.security import check_password_hash

        setup_client.post(
            "/setup/",
            data={
                "step": "1",
                "password": "admin123",
                "confirm_password": "admin123",
                "admin_verify_enabled": "on",
            },
        )
        with setup_client.session_transaction() as sess:
            stored = sess.get("setup_password")
        # 不是明文
        assert stored != "admin123"
        # 是 werkzeug 哈希，可用原明文校验通过
        assert stored.startswith(("pbkdf2:", "scrypt:"))
        assert check_password_hash(stored, "admin123")

    def test_step1_then_step2_plaintext_password_can_login(self, setup_client):
        """完整两步流程：入库密码只用 session 中的哈希一次，明文可校验通过（I2 不二次哈希）。"""
        from werkzeug.security import check_password_hash

        from Module.common.db_utils import execute, query

        execute("DELETE FROM users")

        setup_client.post(
            "/setup/",
            data={
                "step": "1",
                "password": "admin123",
                "confirm_password": "admin123",
                "admin_verify_enabled": "on",
            },
        )
        resp = setup_client.post(
            "/setup/",
            data={"step": "2", "server_name": "TestServer"},
        )
        assert resp.status_code == 302

        rows = query("SELECT password FROM users WHERE username = 'admin'")
        assert len(rows) == 1
        assert check_password_hash(rows[0]["password"], "admin123")

    def test_admin_verify_disabled_stores_false(self, setup_client):
        """Unchecked admin_verify_enabled stores False in session."""
        setup_client.post(
            "/setup/",
            data={
                "step": "1",
                "password": "admin456",
                "confirm_password": "admin456",
            },
        )
        with setup_client.session_transaction() as sess:
            assert sess.get("setup_password") != "admin456"
            assert sess.get("setup_admin_verify") is False

    def test_empty_password_rejected(self, setup_client):
        """空密码/缺失密码字段 → step 1 返回"密码不能为空"，不写 session（I2）。"""
        resp = setup_client.post(
            "/setup/",
            data={
                "step": "1",
                "password": "",
                "confirm_password": "",
                "admin_verify_enabled": "on",
            },
        )
        assert resp.status_code == 200
        html = resp.data.decode()
        assert "密码不能为空" in html
        with setup_client.session_transaction() as sess:
            assert "setup_password" not in sess

    def test_redirect_when_config_exists(self, setup_app):
        """GET /setup/ redirects to login if config already exists."""
        JSON_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text("{}")
        try:
            client = setup_app.test_client()
            resp = client.get("/setup/")
            assert resp.status_code == 302
            assert "/user/login" in resp.headers.get("Location", "")
        finally:
            if CONFIG_FILE.exists():
                os.remove(str(CONFIG_FILE))


class TestSetupStep2:
    """Test initial setup step 2: set server name."""

    def _clear_users_table(self):
        """Clear the users table so step 2 INSERT succeeds."""
        from Module.common.db_utils import execute

        execute("DELETE FROM users")

    def test_post_step2_creates_admin_user(self, setup_client):
        """POST step 2 creates admin user in database."""
        # Clear existing users so INSERT id=1 succeeds
        self._clear_users_table()

        # First complete step 1
        resp1 = setup_client.post(
            "/setup/",
            data={
                "step": "1",
                "password": "admin123",
                "confirm_password": "admin123",
                "admin_verify_enabled": "on",
            },
        )
        assert resp1.status_code == 200

        # Complete step 2
        resp = setup_client.post(
            "/setup/",
            data={
                "step": "2",
                "server_name": "TestServer",
            },
        )

        # Should redirect to login
        assert resp.status_code == 302
        assert "/user/login" in resp.headers.get("Location", "")

        # Verify admin user was created
        from Module.common.db_utils import query

        users = query("SELECT * FROM users WHERE username = 'admin'")
        assert len(users) == 1
        assert users[0]["role"] == "admin"
        assert users[0]["is_superadmin"] == 1

    def test_post_step2_stores_hashed_admin_password(self, setup_client):
        """POST step 2 创建的管理员密码以 werkzeug 哈希存储（bug #16 统一哈希方案）。"""
        from werkzeug.security import check_password_hash

        from Module.common.db_utils import query

        self._clear_users_table()

        setup_client.post(
            "/setup/",
            data={
                "step": "1",
                "password": "admin123",
                "confirm_password": "admin123",
                "admin_verify_enabled": "on",
            },
        )
        resp = setup_client.post(
            "/setup/",
            data={
                "step": "2",
                "server_name": "TestServer",
            },
        )
        assert resp.status_code == 302

        rows = query("SELECT password FROM users WHERE username = 'admin'")
        assert len(rows) == 1
        stored = rows[0]["password"]
        assert stored.startswith(("pbkdf2:", "scrypt:"))
        # 存储哈希能用原密码校验通过
        assert check_password_hash(stored, "admin123")

    def test_post_step2_creates_config_file(self, setup_client):
        """POST step 2 creates config.json file."""
        self._clear_users_table()

        # First complete step 1
        setup_client.post(
            "/setup/",
            data={
                "step": "1",
                "password": "admin123",
                "confirm_password": "admin123",
                "admin_verify_enabled": "on",
            },
        )

        # Complete step 2
        resp = setup_client.post(
            "/setup/",
            data={
                "step": "2",
                "server_name": "TestServer",
            },
        )

        # Should redirect to login
        assert resp.status_code == 302
        assert "/user/login" in resp.headers.get("Location", "")

        # Verify config file was created
        assert CONFIG_FILE.exists()

        # Verify config content
        from Module.common.file_utils import read_json_file

        config = read_json_file(CONFIG_FILE)
        assert config is not None
        assert config["config"]["server_name"] == "TestServer"
        assert config["settings"]["admin_verify_enabled"] is True

    def test_non_setup_prefix_not_exempt_from_setup_check(self, setup_client):
        """/setupfoo 等非 setup 前缀路径不得被 startswith('/setup') 误豁免：
        首次部署（config 缺失）时必须回到 /setup 向导，而不是漏给路由层（404）或登录页。"""
        resp = setup_client.get("/setupfoo")
        assert resp.status_code == 302  # 红灯：当前被误豁免 → 掉到路由层 404
        assert "/setup" in resp.headers.get("Location", "")

    def test_post_step2_clears_session(self, setup_client):
        """POST step 2 clears setup data from session."""
        self._clear_users_table()

        # First complete step 1
        setup_client.post(
            "/setup/",
            data={
                "step": "1",
                "password": "admin123",
                "confirm_password": "admin123",
                "admin_verify_enabled": "on",
            },
        )

        # Verify session has setup data
        with setup_client.session_transaction() as sess:
            assert "setup_password" in sess
            assert "setup_admin_verify" in sess

        # Complete step 2
        resp = setup_client.post(
            "/setup/",
            data={
                "step": "2",
                "server_name": "TestServer",
            },
        )

        # Verify session was cleared
        with setup_client.session_transaction() as sess:
            assert "setup_password" not in sess
            assert "setup_admin_verify" not in sess

    def test_post_step2_with_default_server_name(self, setup_client):
        """POST step 2 with default server name uses 'Web'."""
        self._clear_users_table()

        # First complete step 1
        setup_client.post(
            "/setup/",
            data={
                "step": "1",
                "password": "admin123",
                "confirm_password": "admin123",
                "admin_verify_enabled": "on",
            },
        )

        # Complete step 2 without server_name
        resp = setup_client.post(
            "/setup/",
            data={
                "step": "2",
            },
        )

        # Should redirect to login
        assert resp.status_code == 302
        assert "/user/login" in resp.headers.get("Location", "")

        # Verify config file was created with default server name
        assert CONFIG_FILE.exists()
        from Module.common.file_utils import read_json_file

        config = read_json_file(CONFIG_FILE)
        assert config["config"]["server_name"] == "Web"
