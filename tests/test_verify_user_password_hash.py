"""
verify_user 密码哈希统一与存量明文自动迁移 测试（bug #16）

覆盖：
- 明文存量用户：明文登录成功，登录后密码列自动迁移为 werkzeug 哈希，迁移后同密码仍可登录
- 哈希存量用户：正确密码登录成功，错误密码登录失败
- 迁移不误伤：明文比较失败时不得改写密码列；被禁用用户不得触发迁移
"""

from werkzeug.security import generate_password_hash

from Module.common import user_utils
from Module.common.db_utils import query


def _make_user(username, password, user_id=1, enabled=True):
    return {
        "id": user_id,
        "username": username,
        "password": password,
        "role": "user",
        "enabled": enabled,
    }


def _stored_password(username):
    """从临时测试库读取指定用户的密码列原始存储值"""
    rows = query("SELECT password FROM users WHERE username = ?", (username,))
    return rows[0]["password"] if rows else None


class TestPlaintextUserMigration:
    """存量明文用户：明文登录成功 + 登录即迁移"""

    def test_plaintext_login_succeeds_and_migrates(self, switch_db):
        user_utils.save_users(
            {"legacy": _make_user("legacy", "old-plain-pw")}
        )

        # 明文密码登录成功
        user = user_utils.verify_user("legacy", "old-plain-pw")
        assert user is not None
        assert user["username"] == "legacy"

        # 登录后库中密码列已迁移为 werkzeug 哈希
        stored = _stored_password("legacy")
        assert stored.startswith(("pbkdf2:", "scrypt:"))

        # 迁移后再用同一密码登录仍成功（走哈希校验路径）
        assert user_utils.verify_user("legacy", "old-plain-pw") is not None

    def test_plaintext_wrong_password_fails(self, switch_db):
        user_utils.save_users(
            {"legacy": _make_user("legacy", "old-plain-pw")}
        )
        assert user_utils.verify_user("legacy", "wrong-pw") is None


class TestHashedUser:
    """存量哈希用户：正确密码成功，错误密码失败"""

    def test_hashed_user_correct_password(self, switch_db):
        user_utils.save_users(
            {
                "hashed": _make_user(
                    "hashed", generate_password_hash("secure-pw"), user_id=2
                )
            }
        )
        user = user_utils.verify_user("hashed", "secure-pw")
        assert user is not None
        assert user["username"] == "hashed"

    def test_hashed_user_wrong_password(self, switch_db):
        user_utils.save_users(
            {
                "hashed": _make_user(
                    "hashed", generate_password_hash("secure-pw"), user_id=2
                )
            }
        )
        assert user_utils.verify_user("hashed", "wrong-pw") is None


class TestNoRewriteOnFailure:
    """迁移不误伤：明文比较失败时不得改写密码列"""

    def test_wrong_password_does_not_rewrite(self, switch_db):
        user_utils.save_users(
            {"legacy": _make_user("legacy", "old-plain-pw")}
        )

        # 连续错误尝试
        assert user_utils.verify_user("legacy", "bad-1") is None
        assert user_utils.verify_user("legacy", "bad-2") is None

        # 密码列保持原明文，未被改写
        assert _stored_password("legacy") == "old-plain-pw"

        # 之后正确密码登录仍成功并迁移
        assert user_utils.verify_user("legacy", "old-plain-pw") is not None
        assert _stored_password("legacy").startswith(("pbkdf2:", "scrypt:"))

    def test_disabled_user_no_migration(self, switch_db):
        """被禁用用户即使密码正确也验证失败，且不得触发迁移"""
        user_utils.save_users(
            {"frozen": _make_user("frozen", "old-plain-pw", user_id=3, enabled=False)}
        )
        assert user_utils.verify_user("frozen", "old-plain-pw") is None
        assert _stored_password("frozen") == "old-plain-pw"
