"""
db_utils SQLite 查询、执行、事务、路径切换、损坏判定 单元测试
"""

import sqlite3

import pytest

from Module.common import db_utils


def test_init_db_creates_all_tables(switch_db):
    """建表后关键表均存在"""
    tables = db_utils.query("SELECT name FROM sqlite_master WHERE type='table'")
    names = {t["name"] for t in tables}
    assert {"users", "books", "activity_log", "active_sessions", "favorites"} <= names


def test_execute_insert_and_lastrowid(switch_db):
    """execute 插入返回最后一行 id 且可查询"""
    rid = db_utils.execute(
        "INSERT INTO books (title, author) VALUES (?,?)", ("三体", "刘慈欣")
    )
    row = db_utils.query("SELECT * FROM books WHERE id=?", (rid,))[0]
    assert row["author"] == "刘慈欣"


def test_executemany_multiple(switch_db):
    """批量插入多行"""
    db_utils.executemany(
        "INSERT INTO books (title, author) VALUES (?,?)",
        [("a", "x"), ("b", "y"), ("c", "z")],
    )
    assert db_utils.query("SELECT COUNT(*) AS c FROM books")[0]["c"] == 3


def test_transaction_commit(switch_db):
    """事务内写操作正常提交"""
    with db_utils.transaction():
        db_utils.execute("INSERT INTO books (title, author) VALUES (?,?)", ("t1", "a"))
    assert db_utils.query("SELECT COUNT(*) AS c FROM books")[0]["c"] == 1


def test_transaction_rollback(switch_db):
    """事务中抛出异常则整体回滚"""

    class Boom(Exception):
        pass

    with pytest.raises(Boom):
        with db_utils.transaction():
            db_utils.execute(
                "INSERT INTO books (title, author) VALUES (?,?)", ("t2", "b")
            )
            raise Boom()
    assert db_utils.query("SELECT COUNT(*) AS c FROM books")[0]["c"] == 0


def test_is_corruption_error():
    """识别损坏类错误，排除约束/语法错误"""
    assert db_utils._is_corruption_error(
        sqlite3.DatabaseError("file is not a database")
    )
    assert db_utils._is_corruption_error(
        sqlite3.DatabaseError("database disk image is malformed")
    )
    assert not db_utils._is_corruption_error(
        sqlite3.DatabaseError("UNIQUE constraint failed")
    )


def test_set_db_path_switches_connection(tmp_path):
    """切换路径并重置后 get_connection 连接到新文件"""
    new_db = tmp_path / "switched.db"
    assert not new_db.exists()
    db_utils.set_db_path(new_db)
    db_utils.reset_state()
    con = db_utils.get_connection()
    row = con.execute("PRAGMA database_list").fetchone()
    assert str(row[2]).endswith("switched.db")
    assert new_db.exists()
    # 测试结束由 autouse db_cleanup 恢复默认路径


def test_ip_bans_table_exists(switch_db):
    """init_db 后 ip_bans 表存在且可写入读取"""
    from Module.common import db_utils

    con = db_utils.get_connection()
    con.executescript(db_utils.SCHEMA)
    con.commit()
    rows = db_utils.query("PRAGMA table_info(ip_bans)")
    columns = [r["name"] for r in rows]
    assert "ip" in columns
    assert "ban_count" in columns
    assert "expires_at" in columns
    assert "is_permanent" in columns
    db_utils.execute(
        "INSERT INTO ip_bans (ip, ban_count, ban_reason, created_at, expires_at, is_permanent) VALUES (?,?,?,?,?,?)",
        ("1.2.3.4", 1, "line1_login", "2026-08-10 10:00:00", "2026-08-10 10:05:00", 0),
    )
    got = db_utils.query("SELECT * FROM ip_bans WHERE ip = ?", ("1.2.3.4",))
    assert got[0]["ban_count"] == 1
