"""
app.py 进程管理命令测试（start / quit / reload 分派与 PID 文件）

不启动真实服务器：分派与状态判定通过 monkeypatch 验证；
真实生命周期由 scripts/verify_cli_commands.py 端到端覆盖。
"""

import app as app_module


class TestCommandDispatch:
    def test_start(self, monkeypatch):
        calls = []
        monkeypatch.setattr(app_module, "_cmd_start", lambda: calls.append("start") or 0)
        assert app_module.main(["start"]) == 0
        assert calls == ["start"]

    def test_quit(self, monkeypatch):
        calls = []
        monkeypatch.setattr(app_module, "_cmd_quit", lambda: calls.append("quit") or 0)
        assert app_module.main(["quit"]) == 0
        assert calls == ["quit"]

    def test_reload(self, monkeypatch):
        calls = []
        monkeypatch.setattr(app_module, "_cmd_reload", lambda: calls.append("reload") or 0)
        assert app_module.main(["reload"]) == 0
        assert calls == ["reload"]


class TestForegroundCompat:
    def test_default_is_debug_foreground(self, monkeypatch):
        seen = {}
        monkeypatch.setattr(
            app_module, "_serve", lambda production_mode: seen.update(p=production_mode)
        )
        assert app_module.main([]) == 0
        assert seen["p"] is False

    def test_production_flag(self, monkeypatch):
        seen = {}
        monkeypatch.setattr(
            app_module, "_serve", lambda production_mode: seen.update(p=production_mode)
        )
        assert app_module.main(["--production"]) == 0
        assert seen["p"] is True


class TestPidFile:
    def test_read_pid_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(app_module, "_PID_FILE", tmp_path / "app.pid")
        assert app_module._read_pid() is None

    def test_read_pid_invalid(self, tmp_path, monkeypatch):
        target = tmp_path / "app.pid"
        target.write_text("not-a-pid", encoding="utf-8")
        monkeypatch.setattr(app_module, "_PID_FILE", target)
        assert app_module._read_pid() is None

    def test_read_pid_ok(self, tmp_path, monkeypatch):
        target = tmp_path / "app.pid"
        target.write_text("4321", encoding="utf-8")
        monkeypatch.setattr(app_module, "_PID_FILE", target)
        assert app_module._read_pid() == 4321

    def test_quit_when_not_running(self, tmp_path, monkeypatch, capsys):
        target = tmp_path / "app.pid"
        target.write_text("4321", encoding="utf-8")
        monkeypatch.setattr(app_module, "_PID_FILE", target)
        monkeypatch.setattr(app_module, "_is_running", lambda pid: False)
        assert app_module._cmd_quit() == 0
        assert "服务未运行" in capsys.readouterr().out
        assert not target.exists()
