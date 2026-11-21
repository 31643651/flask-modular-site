"""
UID 分区模型 / 超管启动迁移强化 / 待遇与保护收窄测试（ADR-0007）
"""
from pathlib import Path

import pytest
from werkzeug.security import generate_password_hash

from Module.common import db_utils

ROOT = Path(__file__).resolve().parents[1]

USER_COLS = "id, username, password, role, enabled, is_superadmin"


@pytest.fixture
def config_file(tmp_path, monkeypatch):
    """将 config.json 重定向到临时文件，避免写生产配置（路由测试需要）"""
    target = tmp_path / "config.json"
    monkeypatch.setattr("Module.common.config_utils.CONFIG_FILE", target)
    return target


def _ins(cols, *rows):
    for r in rows:
        db_utils.execute(f"INSERT INTO users ({cols}) VALUES (?,?,?,?,?,?)", r)


def _row(uid):
    r = db_utils.query("SELECT * FROM users WHERE id = ?", (uid,))
    assert len(r) == 1
    return r[0]


class TestStartupMigration:
    def test_0to9_promoted_and_forced_enabled(self, switch_db):
        """0-9 即使原 role=user、enabled=0，启动后被提权 admin+启用+超管（R1）"""
        _ins(USER_COLS,
             (0, "u0", generate_password_hash("p"), "user", 0, 0),
             (7, "u7", generate_password_hash("p"), "user", 1, 0),
             (9, "u9", generate_password_hash("p"), "user", 0, 0))
        db_utils._migrate_superadmin()
        for uid in (0, 7, 9):
            r = _row(uid)
            assert r["role"] == "admin"
            assert r["is_superadmin"] == 1
            assert r["enabled"] == 1  # 强制启用

    def test_out_of_range_superadmin_purged(self, switch_db):
        """id>9 且 is_superadmin=1 → 清退 enabled=0/is_superadmin=0（R2）"""
        _ins(USER_COLS,
             (50, "eve", generate_password_hash("p"), "admin", 1, 1),
             (1001, "frank", generate_password_hash("p"), "user", 1, 1))
        db_utils._migrate_superadmin()
        for uid in (50, 1001):
            r = _row(uid)
            assert r["enabled"] == 0
            assert r["is_superadmin"] == 0

    def test_plain_user_gt9_untouched(self, switch_db):
        """id>9 普通 user/api（is_superadmin=0）不受影响"""
        _ins(USER_COLS,
             (50, "bob", generate_password_hash("p"), "user", 1, 0),
             (1001, "carl", generate_password_hash("p"), "api", 1, 0))
        db_utils._migrate_superadmin()
        assert _row(50)["enabled"] == 1 and _row(50)["role"] == "user"
        assert _row(1001)["enabled"] == 1 and _row(1001)["role"] == "api"

    def test_migration_idempotent(self, switch_db):
        """跑两次结果一致"""
        _ins(USER_COLS,
             (3, "g", generate_password_hash("p"), "user", 0, 0),
             (60, "h", generate_password_hash("p"), "admin", 1, 1))
        db_utils._migrate_superadmin()
        first = (_row(3)["role"], _row(3)["enabled"], _row(60)["enabled"], _row(60)["is_superadmin"])
        db_utils._migrate_superadmin()
        second = (_row(3)["role"], _row(3)["enabled"], _row(60)["enabled"], _row(60)["is_superadmin"])
        assert first == second
        assert first == ("admin", 1, 0, 0)


def _usable_admin_count():
    return len(db_utils.query(
        "SELECT 1 FROM users WHERE role='admin' AND enabled=1 AND is_superadmin=1"
    ))


class TestEnsureAdminAlignment:
    def test_promote_relocates_gt9_to_0to9(self, switch_db):
        """无可用超管、最老用户 id>9 → 重定位到 0-9 最小空位（id=0）"""
        from Module.common.user_utils import ensure_admin_exists
        _ins(USER_COLS, (20, "oldest", generate_password_hash("pw"), "user", 1, 0))
        status = ensure_admin_exists()
        assert status == "promoted"
        r0 = _row(0)
        assert r0["username"] == "oldest"
        assert r0["role"] == "admin" and r0["is_superadmin"] == 1 and r0["enabled"] == 1
        # 原 id=20 行已不存在
        assert db_utils.query("SELECT 1 FROM users WHERE id=20") == []

    def test_restore_relocates_gt9_admin(self, switch_db):
        """admin 行存在但 id>9 且不可用 → 重定位到 0-9 最小空位"""
        from Module.common.user_utils import ensure_admin_exists
        _ins(USER_COLS, (30, "admin", generate_password_hash("pw"), "user", 0, 0))
        status = ensure_admin_exists()
        assert status == "restored"
        r0 = _row(0)
        assert r0["username"] == "admin"
        assert r0["role"] == "admin" and r0["is_superadmin"] == 1 and r0["enabled"] == 1
        assert db_utils.query("SELECT 1 FROM users WHERE id=30") == []

    def test_create_admin_in_0to9_when_empty(self, switch_db):
        """表空 → 创建 admin 落在 0-9 最小空位（id=0）"""
        from Module.common.user_utils import ensure_admin_exists
        status = ensure_admin_exists()
        assert status == "created"
        r0 = _row(0)
        assert r0["username"] == "admin" and r0["is_superadmin"] == 1

    def test_inplace_restore_when_already_0to9(self, switch_db):
        """admin 行 id 已在 0-9 仅被降级 → 原地恢复，不改 id"""
        from Module.common.user_utils import ensure_admin_exists
        _ins(USER_COLS, (2, "admin", generate_password_hash("pw"), "user", 0, 0))
        status = ensure_admin_exists()
        assert status == "restored"
        r2 = _row(2)
        assert r2["username"] == "admin" and r2["role"] == "admin"
        assert _usable_admin_count() == 1


class TestRegisterUid:
    def _svc(self):
        from Module.core.admin_service import AdminService
        return AdminService()

    def _all_users(self):
        from Module.common import user_utils
        return user_utils.load_users()

    def test_auto_admin_starts_at_11(self, switch_db):
        svc = self._svc()
        ok, _ = svc.register_user("adm1", "pw", role="admin")
        assert ok
        u = self._all_users()["adm1"]
        assert u["id"] == 11 and u["role"] == "admin"
        assert not u.get("is_superadmin")

    def test_auto_nonadmin_starts_at_1001(self, switch_db):
        svc = self._svc()
        ok, _ = svc.register_user("bob", "pw", role="user")
        assert ok
        u = self._all_users()["bob"]
        assert u["id"] == 1001 and u["role"] == "user"

    def test_manual_admin_in_range(self, switch_db):
        svc = self._svc()
        ok, _ = svc.register_user("adm2", "pw", role="admin", uid=42)
        assert ok and self._all_users()["adm2"]["id"] == 42

    def test_manual_admin_out_of_range_rejected(self, switch_db):
        svc = self._svc()
        for bad in (500, 2000):
            ok, msg = svc.register_user(f"adm_{bad}", "pw", role="admin", uid=bad)
            assert ok is False and "11-99" in msg, msg

    def test_manual_reserved_rejected(self, switch_db):
        svc = self._svc()
        for bad in (0, 5, 9, 10):
            ok, msg = svc.register_user(f"r_{bad}", "pw", role="user", uid=bad)
            assert ok is False and "保留" in msg, msg

    def test_manual_nonadmin_any_valid_band(self, switch_db):
        svc = self._svc()
        for good in (11, 99, 100, 1000, 1001):
            ok, _ = svc.register_user(f"n_{good}", "pw", role="user", uid=good)
            assert ok is True, good
            assert self._all_users()[f"n_{good}"]["id"] == good

    def test_manual_uid_taken_rejected(self, switch_db):
        svc = self._svc()
        assert svc.register_user("a", "pw", role="user", uid=1001)[0]
        ok, msg = svc.register_user("b", "pw", role="user", uid=1001)
        assert ok is False and "已被占用" in msg, msg

    def test_new_user_never_superadmin(self, switch_db):
        svc = self._svc()
        svc.register_user("c", "pw", role="admin", uid=20)
        u = self._all_users()["c"]
        assert not u.get("is_superadmin")

    def test_route_passes_uid(self, client, app, config_file):
        """路由层透传 uid 到 register_user（后端为权威）"""
        from Module.common import user_utils

        user_utils.save_users({
            "admin": {"id": 0, "username": "admin", "password": "p",
                      "role": "admin", "enabled": True, "is_superadmin": True},
        })
        with client.session_transaction() as sess:
            sess["user_id"] = 0
            sess["username"] = "admin"
            sess["role"] = "admin"
            sess["verified"] = True
            sess["csrf_token"] = "tuid"
        resp = client.post(
            "/admin/users/register",
            json={"username": "uiduser", "password": "pw123",
                  "role": "user", "uid": 1005},
            headers={"X-CSRF-Token": "tuid"},
        )
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True
        assert user_utils.load_users()["uiduser"]["id"] == 1005


def _login(client, username, role, uid, verified=True):
    """写入用户 + 注入登录态（verified 控制动态验证状态）"""
    from Module.common import user_utils

    user_utils.save_users({username: {
        "id": uid, "username": username, "password": "p",
        "role": role, "enabled": True,
        "is_superadmin": 1 if (role == "admin" and uid <= 9) else 0,
    }})
    with client.session_transaction() as s:
        s["user_id"] = uid
        s["username"] = username
        s["role"] = role
        s["verified"] = verified


class TestPrivilegeNarrowing:
    def test_regular_admin_no_verify_page(self, client, app):
        """id=50 role=admin 普通管理员访问 /user/verify 被重定向 login（非超管）"""
        _login(client, "regadm", "admin", 50, verified=False)
        resp = client.get("/user/verify")
        assert resp.status_code == 302 and resp.location.endswith("/user/login")

    def test_superadmin_verify_page_renders(self, client, app):
        """id=0 role=admin 超管访问 /user/verify 渲染（未验证）"""
        _login(client, "root", "admin", 0, verified=False)
        resp = client.get("/user/verify")
        assert resp.status_code == 200

    def test_regular_admin_protected_no_verify_needed(self, client, app):
        """id=50 普通管理员未验证也能访问受保护首页（不需动态验证）"""
        _login(client, "regadm", "admin", 50, verified=False)
        resp = client.get("/")
        assert resp.status_code == 200

    def test_superadmin_unverified_blocked_on_protected(self, client, app):
        """id=0 超管未验证访问受保护首页被拦截（跳验证）"""
        _login(client, "root", "admin", 0, verified=False)
        resp = client.get("/")
        assert resp.status_code == 302

    def test_regular_admin_feedback_limited(self, switch_db):
        """id=50 role=admin 普通管理员反馈受 3 次限制（收窄，非 -1）"""
        from Module.common import user_utils
        from Module.userfix import userfix as um

        user_utils.save_users({"regadm": {
            "id": 50, "username": "regadm", "password": "p",
            "role": "admin", "enabled": True, "is_superadmin": 0,
        }})
        ok, remaining = um.check_submission_limit("regadm")
        assert ok is True and remaining == 3  # 受限，非 -1

    def test_superadmin_feedback_unlimited(self, switch_db):
        """id=0 role=admin 超管反馈不限次"""
        from Module.common import user_utils
        from Module.userfix import userfix as um

        user_utils.save_users({"root": {
            "id": 0, "username": "root", "password": "p",
            "role": "admin", "enabled": True, "is_superadmin": 1,
        }})
        ok, remaining = um.check_submission_limit("root")
        assert ok is True and remaining == -1


class TestProtectionNarrowing:
    def _svc(self):
        from Module.core.admin_service import AdminService
        return AdminService()

    @staticmethod
    def _seed_two():
        """超管 root(id=0) + 普通管理员 regadm(id=50)"""
        from Module.common import user_utils

        user_utils.save_users({
            "root": {"id": 0, "username": "root", "password": "p", "role": "admin",
                     "enabled": True, "is_superadmin": 1},
            "regadm": {"id": 50, "username": "regadm", "password": "p", "role": "admin",
                       "enabled": True, "is_superadmin": 0},
        })

    @staticmethod
    def _seed_two_super():
        """两个超管 root(id=0) + boss(id=3)"""
        from Module.common import user_utils

        user_utils.save_users({
            "root": {"id": 0, "username": "root", "password": "p", "role": "admin",
                     "enabled": True, "is_superadmin": 1},
            "boss": {"id": 3, "username": "boss", "password": "p", "role": "admin",
                     "enabled": True, "is_superadmin": 1},
        })

    def test_superadmin_can_disable_regular_admin(self, switch_db):
        """超管可禁用普通管理员（id=50，收窄后不受保护）"""
        from Module.common import user_utils

        self._seed_two()
        ok, _ = self._svc().toggle_user_status("regadm", "root")
        assert ok is True
        assert user_utils.load_users()["regadm"]["enabled"] is False

    def test_superadmin_can_delete_regular_admin(self, switch_db):
        """超管可删除普通管理员"""
        from Module.common import user_utils

        self._seed_two()
        ok, _ = self._svc().delete_user("regadm", "root")
        assert ok is True
        assert "regadm" not in user_utils.load_users()

    def test_cannot_disable_other_superadmin(self, switch_db):
        """不可禁用其他超管（id=3，0-9 保护）"""
        self._seed_two_super()
        ok, msg = self._svc().toggle_user_status("boss", "root")
        assert ok is False and "超级管理员" in msg, msg

    def test_cannot_delete_other_superadmin(self, switch_db):
        """不可删除其他超管"""
        self._seed_two_super()
        ok, msg = self._svc().delete_user("boss", "root")
        assert ok is False and "超级管理员" in msg, msg

    def test_cannot_operate_self(self, switch_db):
        """不可禁用/删除自己（保留）"""
        from Module.common import user_utils

        self._seed_two()
        ok, msg = self._svc().toggle_user_status("root", "root")
        assert ok is False and "自己" in msg, msg
        ok, msg = self._svc().delete_user("root", "root")
        assert ok is False and "自己" in msg, msg
        assert "root" in user_utils.load_users()


class TestRegisterFormUidField:
    TEMPLATE = ROOT / "Module/admin/templates/admin/users.html"

    def test_uid_input_present(self):
        """注册表单含可选 UID 输入框"""
        src = self.TEMPLATE.read_text(encoding="utf-8")
        assert 'id="newUid"' in src, "注册表单缺少 UID 输入框"

    def test_register_sends_uid(self):
        """registerUser 提交体必须携带 uid（后端为权威）"""
        import re

        src = self.TEMPLATE.read_text(encoding="utf-8")
        assert "newUid" in src
        m = re.search(r"function registerUser\(event\)\s*\{([\s\S]*?)\n        \}", src)
        assert m, "registerUser 函数缺失"
        assert "uid" in m.group(1) and "newUid" in m.group(1)
