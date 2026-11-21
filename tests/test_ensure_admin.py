"""
启动期 admin 账户常驻兜底测试（ADR-0003）
"""

from werkzeug.security import check_password_hash, generate_password_hash

from Module.common import db_utils

ADMIN_COLS = "id, username, password, role, enabled, is_superadmin"


def _one(sql, params=()):
    rows = db_utils.query(sql, params)
    assert len(rows) == 1
    return rows[0]


def test_restore_demoted_admin_row(switch_db):
    """admin 行被降级/禁用 → 恢复 role/启用/超管，密码保留可直接登录"""
    from Module.common.user_utils import ensure_admin_exists

    db_utils.execute(
        f"INSERT INTO users ({ADMIN_COLS}) VALUES (?, ?, ?, ?, ?, ?)",
        (1, "admin", generate_password_hash("adminpw"), "user", 0, 0),
    )
    status = ensure_admin_exists()
    row = _one("SELECT * FROM users WHERE username = 'admin'")
    assert status == "restored"
    assert row["role"] == "admin"
    assert row["enabled"] == 1
    assert row["is_superadmin"] == 1
    assert check_password_hash(row["password"], "adminpw")  # 密码原样保留


def test_promote_oldest_user_when_admin_row_missing(switch_db):
    """无 admin 行但有其他用户 → 最老者被提权并重定位到 0-9 最小空位（ADR-0007），用户名与密码保留"""
    from Module.common.user_utils import ensure_admin_exists

    db_utils.execute(
        f"INSERT INTO users ({ADMIN_COLS}) VALUES (?, ?, ?, ?, ?, ?)",
        (9, "zoe", generate_password_hash("zoepw"), "user", 1, 0),
    )
    db_utils.execute(
        f"INSERT INTO users ({ADMIN_COLS}) VALUES (?, ?, ?, ?, ?, ?)",
        (5, "alice", generate_password_hash("alicepw"), "user", 1, 0),
    )
    status = ensure_admin_exists()
    # 兜底超管必须落在 0-9 最小空位（id=0），而非原地 id=5
    row = _one("SELECT * FROM users WHERE id = 0")
    assert status == "promoted"
    assert row["username"] == "alice"  # 登录方式不变
    assert row["role"] == "admin"
    assert row["enabled"] == 1
    assert row["is_superadmin"] == 1
    assert check_password_hash(row["password"], "alicepw")
    # 原 id=5 行已被重定位走
    assert db_utils.query("SELECT 1 FROM users WHERE id = 5") == []
    # 非最老用户不被提权
    other = _one("SELECT * FROM users WHERE id = 9")
    assert other["role"] == "user"


def test_create_admin_when_users_table_empty(switch_db):
    """users 表为空 → 创建 admin（随机密码以哈希存储，明文打到启动日志）"""
    from Module.common.user_utils import ensure_admin_exists

    status = ensure_admin_exists()
    row = _one("SELECT * FROM users WHERE username = 'admin'")
    assert status == "created"
    assert row["role"] == "admin"
    assert row["enabled"] == 1
    assert row["is_superadmin"] == 1
    # 存储为 werkzeug 哈希，而非明文随机串
    assert row["password"].startswith(("pbkdf2:", "scrypt:"))


def test_noop_when_usable_admin_exists_under_other_name(switch_db):
    """已有改名后的可用超管 → 不再制造第二个管理员（最老普通用户保持原样）"""
    from Module.common.user_utils import ensure_admin_exists

    db_utils.execute(
        f"INSERT INTO users ({ADMIN_COLS}) VALUES (?, ?, ?, ?, ?, ?)",
        (1, "alice", generate_password_hash("alicepw"), "user", 1, 0),
    )
    db_utils.execute(
        f"INSERT INTO users ({ADMIN_COLS}) VALUES (?, ?, ?, ?, ?, ?)",
        (3, "root", generate_password_hash("rootpw"), "admin", 1, 1),
    )
    status = ensure_admin_exists()
    assert status == "exists"
    row = _one("SELECT * FROM users WHERE id = 1")
    assert row["role"] == "user"  # 未被越权提权
