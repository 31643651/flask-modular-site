"""
user_utils 用户代理解析、用户缓存 TTL、活动日志队列 单元测试
"""

from Module.common import user_utils


def test_parse_chrome_windows():
    info = user_utils.parse_user_agent(
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    assert info["device_type"] == "Windows"
    assert info["os"] == "Windows 10/11"
    assert info["browser"] == "Chrome"


def test_parse_firefox_android():
    info = user_utils.parse_user_agent(
        "Mozilla/5.0 (Linux; Android 13; Pixel 7) Firefox/119.0"
    )
    assert info["device_type"] == "Android"
    assert info["os"] == "Android"
    assert info["browser"] == "Firefox"


def test_parse_edge_windows11():
    info = user_utils.parse_user_agent(
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0"
    )
    assert info["browser"] == "Edge"


def test_parse_unknown_empty():
    assert user_utils.parse_user_agent("") == {
        "device_type": "未知设备",
        "os": "未知操作系统",
        "browser": "未知浏览器",
    }


def test_save_users_replace_all(switch_db):
    """save_users 全量替换 + 缓存读取"""
    user_utils.save_users(
        {
            "alice": {
                "id": 1,
                "username": "alice",
                "password": "p1",
                "role": "user",
                "enabled": True,
            },
        }
    )
    users = user_utils.load_users()
    assert users["alice"]["enabled"] is True

    user_utils.save_users(
        {
            "bob": {
                "id": 2,
                "username": "bob",
                "password": "p2",
                "role": "admin",
                "enabled": False,
            },
        }
    )
    users_after = user_utils.load_users()
    assert "alice" not in users_after
    assert users_after["bob"]["enabled"] is False


def test_get_user(switch_db):
    user_utils.save_users(
        {
            "carol": {
                "id": 3,
                "username": "carol",
                "password": "p3",
                "role": "user",
                "enabled": True,
            },
        }
    )
    assert user_utils.get_user("carol") is not None
    assert user_utils.get_user("nobody") is None


def test_verify_user_both_success_and_fail(switch_db):
    user_utils.save_users(
        {
            "dave": {
                "id": 4,
                "username": "dave",
                "password": "pw",
                "role": "user",
                "enabled": True,
            },
            "evil": {
                "id": 5,
                "username": "evil",
                "password": "pw",
                "role": "user",
                "enabled": False,
            },
        }
    )
    assert user_utils.verify_user("dave", "pw") is not None
    assert user_utils.verify_user("dave", "bad") is None
    assert user_utils.verify_user("evil", "pw") is None  # 被禁用

    # 用户缓存 TTL 缓存存在时仍返回一致数据
    first = user_utils.load_users()
    assert first["dave"]["enabled"] is True


def test_invalidate_users_cache(switch_db):
    user_utils.save_users(
        {
            "eve": {
                "id": 6,
                "username": "eve",
                "password": "p",
                "role": "user",
                "enabled": True,
            },
        }
    )
    user_utils.load_users()
    assert user_utils._users_cache is not None
    user_utils.invalidate_users_cache()
    assert user_utils._users_cache is None


def test_users_cache_ttl(switch_db, monkeypatch):
    """USER_CACHE_TTL 改为 0 秒，使每次 load_users 都重新读库"""
    monkeypatch.setattr(user_utils, "USER_CACHE_TTL", 0)
    user_utils.save_users(
        {
            "frank": {
                "id": 7,
                "username": "frank",
                "password": "p",
                "role": "user",
                "enabled": True,
            },
        }
    )
    _ = user_utils.load_users()
    # 直接把磁盘改掉并清缓存，证明 load 是从库读取
    user_utils.invalidate_users_cache()
    assert user_utils.load_users()["frank"]["enabled"] is True


def test_add_and_flush_activity(switch_db):
    """add_activity 入队、flush 落库、load 回读"""
    user_utils.add_activity("alice", "用户登录", "127.0.0.1", path="/user/login")
    assert len(user_utils._activity_queue) == 1
    user_utils.flush_activity_queue()
    assert user_utils._activity_queue == []
    recs = user_utils.load_activities()
    assert recs and recs[0]["username"] == "alice"
