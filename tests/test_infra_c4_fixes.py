"""
基础设施小修四项测试（bug #22 + #23 + #24 + #25）：

- #22 file_utils：mkdir 失败时 write_json_file 返回 False 而非抛 NameError
- #23 admin 重启：Windows 分支用 subprocess.Popen + sys.exit，非 Windows 保持 os.execv
- #24 活动日志清理：无法解析的时间记录不再被误删
- #25 db_utils：重建周期内再次损坏被短路，递归终止
"""

import sqlite3
import sys
from pathlib import Path

import pytest

from Module.common import db_utils, file_utils, user_utils

CSRF_TOKEN = "test-csrf-token"


# ============================================================================
# #22 file_utils write_json_file 异常路径
# ============================================================================


class TestWriteJsonFileMkdirFailure:
    def test_mkdir_failure_returns_false_not_nameerror(self, tmp_path, monkeypatch):
        """mkdir 失败（目录无法创建）→ 返回 False，不再抛 NameError"""
        target = tmp_path / "sub" / "data.json"

        def _fail_mkdir(self, *args, **kwargs):
            raise OSError("disk full")

        monkeypatch.setattr(Path, "mkdir", _fail_mkdir)

        result = file_utils.write_json_file(target, {"a": 1})

        assert result is False

    def test_normal_write_still_works(self, tmp_path):
        """正常写入回归：成功返回 True 且内容正确"""
        target = tmp_path / "normal.json"

        assert file_utils.write_json_file(target, {"b": 2}) is True
        assert file_utils.read_json_file(target) == {"b": 2}


# ============================================================================
# #23 admin 重启路由
# ============================================================================


def _login_superadmin(client):
    user_utils.save_users(
        {
            "admin": {
                "id": 0,
                "username": "admin",
                "password": "p",
                "role": "admin",
                "enabled": True,
            }
        }
    )
    with client.session_transaction() as sess:
        sess["user_id"] = 0
        sess["username"] = "admin"
        sess["role"] = "admin"
        sess["verified"] = True
        sess["csrf_token"] = CSRF_TOKEN


@pytest.fixture
def config_file(tmp_path, monkeypatch):
    """将 config.json 重定向到临时文件，避免读生产配置"""
    target = tmp_path / "config.json"
    monkeypatch.setattr("Module.common.config_utils.CONFIG_FILE", target)
    return target


class TestRestartRoute:
    def test_windows_branch_uses_popen_and_hard_exit(
        self, client, app, config_file, monkeypatch
    ):
        """Windows 分支：Popen 以 [sys.executable] + sys.argv 启动新实例，os._exit(0) 硬终止当前进程。

        说明：app.run() 线程模式下请求在非主线程处理，sys.exit 只终止该线程、
        父进程存活且端口不释放，重启会静默失效——必须用 os._exit 终止整个进程。
        """
        _login_superadmin(client)
        popen_calls = []
        exit_calls = []
        sysexit_calls = []
        execv_calls = []

        def _fake_popen(args, **kwargs):
            popen_calls.append(args)
            return None

        def _fake_hard_exit(code=0):
            # 模拟 os._exit：记录后以 SystemExit 终止请求（真实 os._exit 终止整个进程、不抛异常）
            exit_calls.append(code)
            raise SystemExit(code)

        def _fake_sysexit(code=0):
            sysexit_calls.append(code)
            raise SystemExit(code)

        def _fake_execv(path, args):
            execv_calls.append((path, args))

        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setattr("subprocess.Popen", _fake_popen)
        monkeypatch.setattr("os._exit", _fake_hard_exit)
        monkeypatch.setattr("sys.exit", _fake_sysexit)
        monkeypatch.setattr("os.execv", _fake_execv)

        with pytest.raises(SystemExit):
            client.post(
                "/admin/restart", headers={"X-CSRF-Token": CSRF_TOKEN}
            )

        assert popen_calls == [[sys.executable] + sys.argv]
        assert exit_calls == [0]
        # 不得再使用 sys.exit（线程级退出无法终止父进程）或 os.execv
        assert sysexit_calls == []
        assert execv_calls == []

    def test_non_windows_branch_keeps_execv(
        self, client, app, config_file, monkeypatch
    ):
        """非 Windows 分支：保持 os.execv，不启用 Popen/sys.exit"""
        _login_superadmin(client)
        popen_calls = []
        exit_calls = []
        execv_calls = []

        def _fake_popen(args, **kwargs):
            popen_calls.append(args)
            return None

        def _fake_exit(code=0):
            exit_calls.append(code)
            raise SystemExit(code)

        def _fake_execv(path, args):
            execv_calls.append((path, args))
            raise SystemExit(0)  # 模拟进程被替换、请求终止

        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setattr("subprocess.Popen", _fake_popen)
        monkeypatch.setattr("sys.exit", _fake_exit)
        monkeypatch.setattr("os.execv", _fake_execv)

        with pytest.raises(SystemExit):
            client.post(
                "/admin/restart", headers={"X-CSRF-Token": CSRF_TOKEN}
            )

        assert execv_calls == [(sys.executable, [sys.executable] + sys.argv)]
        assert popen_calls == []
        assert exit_calls == []


# ============================================================================
# #24 活动日志清理不误删异常时间记录
# ============================================================================


def _act(username, description, time):
    return {
        "username": username,
        "description": description,
        "time": time,
        "ip": "1.2.3.4",
        "path": "/",
        "device_type": "Windows",
        "os": "Windows 10/11",
        "browser": "Chrome",
        "is_logged_in": True,
    }


class TestCleanupKeepsUnparsableTime:
    def test_unparsable_time_not_deleted(self, client, app):
        """无法解析的时间记录被保留，只清理真正过期的记录"""
        _login_superadmin(client)
        user_utils.save_activities(
            [
                _act("alice", "过期记录", "2020-01-01 09:00:00"),
                _act("alice", "异常时间记录", "not-a-time"),
                _act("alice", "近期记录", "2099-01-01 09:00:00"),
            ]
        )

        resp = client.post(
            "/admin/activity/api/cleanup",
            json={"days": 1},
            headers={"X-CSRF-Token": CSRF_TOKEN},
        )

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        # 仅过期记录被删除；异常时间记录与近期记录保留
        assert data["deleted_count"] == 1
        descriptions = [a["description"] for a in user_utils.load_activities()]
        assert "过期记录" not in descriptions
        assert "异常时间记录" in descriptions
        assert "近期记录" in descriptions


# ============================================================================
# #25 db_utils 重建短路
# ============================================================================


CORRUPTION = sqlite3.DatabaseError("database disk image is malformed")


class _AlwaysCorruptConn:
    """所有操作均抛损坏错误的假连接（模拟二次损坏）"""

    def execute(self, sql, params=()):
        raise CORRUPTION

    def executemany(self, sql, seq):
        raise CORRUPTION

    def executescript(self, script):
        raise CORRUPTION

    def commit(self):
        pass

    def close(self):
        pass


class _SchemaOkQueryCorruptConn:
    """建表成功、但后续任何查询/写入均损坏的假连接（模拟反复损坏的存储层）"""

    def execute(self, sql, params=()):
        raise CORRUPTION

    def executemany(self, sql, seq):
        raise CORRUPTION

    def executescript(self, script):
        pass

    def commit(self):
        pass

    def close(self):
        pass


@pytest.fixture
def broken_db_env(tmp_path, monkeypatch):
    """将 DB_FILE 重定向到临时文件并清理模块级状态"""
    monkeypatch.setattr("Module.common.db_utils.DB_FILE", tmp_path / "broken.db")
    monkeypatch.setattr(db_utils, "_connection", None)
    monkeypatch.setattr(db_utils, "_rebuilding", False)
    return tmp_path


class TestDbRebuildShortCircuit:
    def test_double_corruption_terminates(self, broken_db_env, monkeypatch):
        """建表再次损坏：init_db 防重入守卫直接抛出，递归终止（init_db 仅调用一次）"""
        init_calls = []
        real_init = db_utils.init_db

        def counting_init():
            init_calls.append(1)
            return real_init()

        monkeypatch.setattr(db_utils, "init_db", counting_init)
        monkeypatch.setattr(db_utils, "get_connection", lambda: _AlwaysCorruptConn())

        with pytest.raises(sqlite3.DatabaseError):
            db_utils.query("SELECT 1")

        assert len(init_calls) == 1
        # 标志被正确复位，不影响后续正常重建
        assert db_utils._rebuilding is False

    def test_repeated_query_corruption_chain_terminates(
        self, broken_db_env, monkeypatch
    ):
        """建表成功但查询反复损坏：短路守卫终止递归链（init_db 不被无限重入）"""
        init_calls = []
        real_init = db_utils.init_db

        def counting_init():
            init_calls.append(1)
            return real_init()

        monkeypatch.setattr(db_utils, "init_db", counting_init)
        monkeypatch.setattr(
            db_utils, "get_connection", lambda: _SchemaOkQueryCorruptConn()
        )

        with pytest.raises(db_utils.DatabaseRebuildingError):
            db_utils.query("SELECT 1")

        assert len(init_calls) == 1
        assert db_utils._rebuilding is False

    def test_short_circuit_does_not_invoke_rebuild(self, broken_db_env, monkeypatch):
        """重建标志置位期间再遇损坏：直接短路，不再触发 _rebuild_db"""
        rebuild_calls = []

        def _fake_rebuild():
            rebuild_calls.append(1)

        monkeypatch.setattr(db_utils, "_rebuilding", True)
        monkeypatch.setattr(db_utils, "_rebuild_db", _fake_rebuild)
        monkeypatch.setattr(db_utils, "get_connection", lambda: _AlwaysCorruptConn())

        with pytest.raises(db_utils.DatabaseRebuildingError):
            db_utils.query("SELECT 1")

        with pytest.raises(db_utils.DatabaseRebuildingError):
            db_utils.execute("UPDATE users SET enabled = 1")

        with pytest.raises(db_utils.DatabaseRebuildingError):
            db_utils.executemany("INSERT INTO users VALUES (?,?,?,?,?,?)", [])

        assert rebuild_calls == []
