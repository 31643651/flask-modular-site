"""
登录路径实时读取用户库测试（ADR-0005）

缓存预热后带外（直改 SQLite）新增的用户必须能立即登录成功，无需等待 TTL、无需重启。
"""

from werkzeug.security import generate_password_hash


def test_out_of_band_insert_login_visible_immediately(switch_db):
    from Module.common import db_utils, user_utils

    # 1. 经应用写入 carol 并预热 30s TTL 缓存
    user_utils.save_users(
        {
            "carol": {
                "id": 1,
                "username": "carol",
                "password": generate_password_hash("carolpw"),
                "role": "user",
                "enabled": True,
            }
        }
    )
    _ = user_utils.load_users()
    assert "dave" not in user_utils.load_users()

    # 2. 带外直改数据库（模拟手工 SQL 插入），不经过 save_users、无失效钩子
    db_utils.execute(
        "INSERT INTO users (id, username, password, role, enabled, is_superadmin) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (2, "dave", generate_password_hash("davepw"), "user", 1, 0),
    )

    # 3. 缓存仍是陈旧的（带外写入不清缓存——这正是原缺陷的前提）
    assert user_utils._users_cache is not None
    assert "dave" not in user_utils._users_cache

    # 4. 登录读路径必须直读库：立即可见
    assert user_utils.verify_user("dave", "davepw") is not None  # 红灯：当前经缓存 → None

    # 5. 回归：既有用户登录不受影响；错密码仍拒绝
    assert user_utils.verify_user("carol", "carolpw") is not None
    assert user_utils.verify_user("dave", "wrong") is None
