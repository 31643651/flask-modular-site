"""
数据库工具模块

提供线程安全的 SQLite 连接、建表与 JSON 数据迁移功能。
所有高频可变数据（用户、书籍、活动日志、会话、收藏）存储于 SQLite。
"""

import atexit
import contextlib
import sqlite3
import threading
from pathlib import Path


# 基础目录路径
BASE_DIR = Path(__file__).parent.parent.parent
# 数据库文件路径
DB_FILE = BASE_DIR / "Module" / "data" / "app.db"

# 线程锁与连接
_lock = threading.RLock()
_connection = None


def _cleanup_connection():
    """进程退出时确保数据库连接正确关闭"""
    global _connection
    with _lock:
        if _connection is not None:
            try:
                _connection.close()
            except Exception:
                pass
            _connection = None


atexit.register(_cleanup_connection)

# 线程本地事务状态
_thread_local = threading.local()


def _get_in_transaction():
    """获取当前线程的事务标志"""
    return getattr(_thread_local, "_in_transaction", False)


def _set_in_transaction(value):
    """设置当前线程的事务标志"""
    _thread_local._in_transaction = value


# 模块级重建标志：防止数据库损坏重建时 init_db 递归自愈
_rebuilding = False


class DatabaseRebuildingError(RuntimeError):
    """
    数据库重建进行中，操作被短路拒绝

    当重建周期内再次检测到损坏（即将递归触发重建）时抛出，
    终止递归并向调用方暴露真实故障（bug #25）。
    """

# 表结构定义
SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user',
    enabled INTEGER NOT NULL DEFAULT 1,
    is_superadmin INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS books (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    author TEXT NOT NULL,
    description TEXT,
    detail TEXT,
    cover TEXT
);

CREATE TABLE IF NOT EXISTS activity_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT,
    description TEXT,
    time TEXT,
    ip TEXT,
    path TEXT,
    device_type TEXT,
    os TEXT,
    browser TEXT,
    is_logged_in INTEGER
);

CREATE TABLE IF NOT EXISTS active_sessions (
    username TEXT PRIMARY KEY,
    ip TEXT,
    user_agent TEXT,
    last_activity TEXT
);

CREATE TABLE IF NOT EXISTS favorites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    path TEXT NOT NULL,
    added_at TEXT
);

CREATE TABLE IF NOT EXISTS ip_bans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ip TEXT NOT NULL UNIQUE,
    ban_count INTEGER DEFAULT 1,
    ban_type TEXT DEFAULT 'temporary',
    ban_reason TEXT DEFAULT '',
    created_at TEXT,
    expires_at TEXT,
    is_permanent INTEGER DEFAULT 0
);
"""


def get_connection():
    """
    获取线程安全的 SQLite 连接（单例，WAL 模式）

    Returns:
        sqlite3.Connection: 数据库连接
    """
    global _connection
    with _lock:
        if _connection is not None:
            # 健康检查：尝试执行简单查询
            try:
                _connection.execute("SELECT 1")
            except Exception:
                # 连接已损坏，重新创建
                try:
                    _connection.close()
                except Exception:
                    pass
                _connection = None

        if _connection is None:
            DB_FILE.parent.mkdir(parents=True, exist_ok=True)
            _connection = sqlite3.connect(str(DB_FILE), check_same_thread=False)
            _connection.row_factory = sqlite3.Row
            _connection.execute("PRAGMA journal_mode=WAL")
        return _connection


def set_db_path(path):
    """
    设置数据库文件路径（供测试隔离切换临时库）

    仅变更 DB_FILE 指向；调用方需再调用 reset_state() 使现有连接按新路径重建。

    Args:
        path: 新的数据库文件路径（str 或 Path）
    """
    global DB_FILE
    with _lock:
        DB_FILE = Path(path)


def reset_state():
    """
    将 db_utils 模块级单例重置为初始状态（供测试隔离）

    关闭并清空现有连接，重置事务与重建标志；之后 get_connection() 按当前
    DB_FILE 重新连接。

    Returns:
        None
    """
    global _connection, _rebuilding
    with _lock:
        if _connection is not None:
            try:
                _connection.close()
            except Exception:
                pass
        _connection = None
        _set_in_transaction(False)
        _rebuilding = False


def _is_corruption_error(exc):
    """
    判断是否为数据库损坏错误（而非 SQL 或约束错误）

    Args:
        exc: 捕获到的 sqlite3.DatabaseError

    Returns:
        bool: 是否为文件损坏类错误
    """
    msg = str(exc).lower()
    matched = any(
        marker in msg
        for marker in (
            "file is not a database",
            "database disk image is malformed",
            "disk i/o error",
        )
    )
    if matched:
        import structlog

        logger = structlog.get_logger(__name__)
        logger.warning("database_corruption_detected", error=str(exc))
    return matched


def query(sql, params=()):
    """
    执行查询，返回 dict 列表

    Args:
        sql: SQL 语句
        params: 查询参数

    Returns:
        list: 查询结果（dict 列表）
    """
    try:
        with _lock:
            return [dict(r) for r in get_connection().execute(sql, params).fetchall()]
    except sqlite3.DatabaseError as e:
        if not _is_corruption_error(e):
            raise
        if _rebuilding:
            # 重建周期内再次损坏：短路拒绝，终止递归并暴露原始错误（bug #25）
            raise DatabaseRebuildingError(
                "数据库正在重建中，查询被拒绝；底层损坏：" + str(e)
            ) from e
        _rebuild_db()
        with _lock:
            return [dict(r) for r in get_connection().execute(sql, params).fetchall()]


def execute(sql, params=()):
    """
    执行写操作并提交

    Args:
        sql: SQL 语句
        params: 参数

    Returns:
        int: 最后插入行的 id
    """
    try:
        with _lock:
            cur = get_connection().execute(sql, params)
            if not _get_in_transaction():
                get_connection().commit()
            return cur.lastrowid
    except sqlite3.DatabaseError as e:
        if not _is_corruption_error(e):
            raise
        if _rebuilding:
            # 重建周期内再次损坏：短路拒绝，终止递归并暴露原始错误（bug #25）
            raise DatabaseRebuildingError(
                "数据库正在重建中，写操作被拒绝；底层损坏：" + str(e)
            ) from e
        _rebuild_db()
        with _lock:
            cur = get_connection().execute(sql, params)
            if not _get_in_transaction():
                get_connection().commit()
            return cur.lastrowid


def executemany(sql, seq):
    """
    批量执行写操作并提交

    Args:
        sql: SQL 语句
        seq: 参数序列
    """
    try:
        with _lock:
            get_connection().executemany(sql, seq)
            if not _get_in_transaction():
                get_connection().commit()
    except sqlite3.DatabaseError as e:
        if not _is_corruption_error(e):
            raise
        if _rebuilding:
            # 重建周期内再次损坏：短路拒绝，终止递归并暴露原始错误（bug #25）
            raise DatabaseRebuildingError(
                "数据库正在重建中，批量写操作被拒绝；底层损坏：" + str(e)
            ) from e
        _rebuild_db()
        with _lock:
            get_connection().executemany(sql, seq)
            if not _get_in_transaction():
                get_connection().commit()


@contextlib.contextmanager
def transaction():
    """
    事务上下文管理器：将多个写操作包裹为单个原子事务

    在事务内，execute/executemany 不自动提交，退出时统一提交或回滚。
    支持嵌套：内层事务使用 SAVEPOINT，内层回滚不影响外层。
    """
    with _lock:
        is_nested = _get_in_transaction()
        _set_in_transaction(True)
        savepoint_name = f"sp_{threading.get_ident()}"
        try:
            if is_nested:
                get_connection().execute(f"SAVEPOINT {savepoint_name}")
            yield
            if is_nested:
                get_connection().execute(f"RELEASE SAVEPOINT {savepoint_name}")
            else:
                get_connection().commit()
        except Exception:
            if is_nested:
                try:
                    get_connection().execute(f"ROLLBACK TO SAVEPOINT {savepoint_name}")
                except Exception:
                    pass
            else:
                get_connection().rollback()
            raise
        finally:
            _set_in_transaction(is_nested)


def init_db():
    """
    初始化数据库：建表；若表为空则从对应 JSON 文件导入历史数据

    若数据库文件损坏导致启动失败，则自动调用 _rebuild_db() 重建自愈。
    """
    global _rebuilding
    with _lock:
        try:
            conn = get_connection()
            conn.executescript(SCHEMA)
            conn.commit()
        except sqlite3.DatabaseError as e:
            if not _is_corruption_error(e):
                raise
            if _rebuilding:
                # 重建过程中再次损坏，无法二次自愈，抛出原始错误
                raise
            _rebuilding = True
            try:
                _rebuild_db()
            finally:
                _rebuilding = False
            return
        _migrate_superadmin()


def _rebuild_db():
    """
    数据库损坏时删除文件并重建，从 JSON 恢复历史数据

    期间置位 _rebuilding（bug #25）：重建周期内任何再次出现的损坏都会被
    query/execute/executemany 的短路守卫与 init_db 的防重入守卫拦截，
    彻底消除递归重建风险。
    """
    global _connection, _rebuilding
    with _lock:
        if _connection is not None:
            try:
                _connection.close()
            except Exception:
                pass
            _connection = None
        for suffix in ("", "-wal", "-shm", "-journal"):
            p = Path(str(DB_FILE) + suffix)
            if p.exists():
                try:
                    p.unlink()
                except Exception:
                    pass
        _rebuilding = True
        try:
            init_db()
        finally:
            _rebuilding = False


def _migrate_superadmin():
    """
    启动期超管权威校正（ADR-0007），幂等：

    1. 补 is_superadmin 列（兼容旧库）。
    2. R1 超管唯一区间：id 0-9 一律 role='admin' / is_superadmin=1 / enabled=1
       （提权 + 强制启用，0-9 即超级管理员，不保留禁用态）。
    3. R2 越界超管清退：id>9 且 is_superadmin=1 的账号一律 enabled=0 / is_superadmin=0
       （防御带外改库给 id>9 账号打超管标记造成双源角色冲突）。

    说明：R2 用 is_superadmin=1 作触发条件而非 role，避免误伤 id>9 的普通 user/api
    （它们 is_superadmin 本就为 0）。必须在 R1 之后执行。
    """
    # 检查 is_superadmin 列是否存在（兼容旧数据库）
    try:
        columns = [row["name"] for row in query("PRAGMA table_info(users)")]
        if "is_superadmin" not in columns:
            execute(
                "ALTER TABLE users ADD COLUMN is_superadmin INTEGER NOT NULL DEFAULT 0"
            )
    except Exception:
        pass

    # R1：0-9 一律提权 + 强制启用
    execute(
        "UPDATE users SET role = 'admin', is_superadmin = 1, enabled = 1 "
        "WHERE id BETWEEN 0 AND 9"
    )
    # R2：越界超管清退禁用
    execute(
        "UPDATE users SET enabled = 0, is_superadmin = 0 "
        "WHERE id > 9 AND is_superadmin = 1"
    )
