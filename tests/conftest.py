"""
pytest 共享 fixtures

负责：
- 为每个测试创建独立临时 SQLite，隔离生产 Module/data/app.db
- 用 create_app 工厂创建应用并注入临时库
- 提供 db_utils/user_utils 模块级状态重置，避免跨测试泄漏
- 统一禁用活动日志后台 flush 线程，避免真实线程与真实库交互
"""

import pytest

from Module.common import db_utils, user_utils

# 捕获生产默认库路径，供 db_cleanup 在测试后恢复
ORIGINAL_DB_FILE = db_utils.DB_FILE


@pytest.fixture(autouse=True)
def db_cleanup():
    """
    每个测试后保持模块级干净：恢复默认库路径并重置 db_utils/user_utils 状态
    """
    yield
    db_utils.DB_FILE = ORIGINAL_DB_FILE
    db_utils.reset_state()
    with user_utils._users_cache_lock:
        user_utils._users_cache = None
        user_utils._users_cache_ts = 0.0
    with user_utils._activity_queue_lock:
        user_utils._activity_queue = []
    user_utils._activity_flush_thread = None
    # ipguard：重置内存频率计数与封禁缓存，避免跨测试残留
    from Module.ipguard import rate_limiter, ban_manager

    rate_limiter.reset_state()
    ban_manager.reset_state()


@pytest.fixture(autouse=True)
def no_flush_thread(monkeypatch):
    """
    所有测试禁用后台 flush 线程，避免 add_activity 触发真实线程与真实数据库
    写入仍可手动调用 flush_activity_queue 验证。
    """
    monkeypatch.setattr(user_utils, "_ensure_flush_thread", lambda: None)


@pytest.fixture
def db_file(tmp_path):
    """每个测试独立临时 SQLite 文件路径（不触碰生产库）"""
    return tmp_path / "test.db"


@pytest.fixture
def switch_db(db_file):
    """
    将 db_utils 切换到临时库并仅建表（不导入生产 JSON 历史数据）；
    测试事件的精确计数始终基于空表；路径与状态由 db_cleanup 在测试后恢复
    """
    db_utils.set_db_path(db_file)
    db_utils.reset_state()
    con = db_utils.get_connection()
    con.executescript(db_utils.SCHEMA)
    con.commit()
    con.close()
    db_utils.reset_state()
    yield db_file


@pytest.fixture
def app(db_file):
    """用 create_app 工厂创建应用，注入临时数据库与测试配置"""
    from app import create_app

    created = create_app(
        config={
            "TESTING": True,
            "SECRET_KEY": "test",
            "JSON_AS_ASCII": False,
        },
        db_path=db_file,
    )
    yield created


@pytest.fixture
def client(app):
    """Flask 测试客户端"""
    return app.test_client()
