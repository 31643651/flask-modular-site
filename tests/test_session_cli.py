"""
session.py 会话与任务生命周期 CLI 测试（任务 D1）

覆盖五个子命令：
- start：降级行为（无 tasks.json / 无 CURRENT_TASK.md / 非 git 目录时不崩溃 exit 0）、
  当前任务打印、残缺清单扫描、AGENTS.md 前 10 行预览
- step：状态更新正确性、--current 写任务卡、错误分支 exit 1
- finish：门禁（注入 pytest 运行器测失败分支）、in_progress 拦截、非法账本 exit 1
- verify：同口径但不检查任务状态
- new-adr：编号自增、模板四节、文件名净化

所有文件操作在 tmp_path 临时目录中进行（session.py 的 --root 参数重定向），
pytest 调用通过注入运行器模拟，不真实执行测试套件。
"""

import json
from pathlib import Path

import pytest

import session


# ============================================================================
# 辅助
# ============================================================================


def _write_ledger(root, tasks):
    """写 tasks.json（ensure_ascii=False，与 _save_ledger 口径一致）"""
    (root / "tasks.json").write_text(
        json.dumps({"tasks": tasks}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _read_ledger(root):
    return json.loads((root / "tasks.json").read_text(encoding="utf-8"))


def _green_runner(root):
    """注入的测试门禁：pytest 通过"""
    return (0, "5 passed in 0.01s")


def _red_runner(root):
    """注入的测试门禁：pytest 失败"""
    return (1, "1 failed, 4 passed in 0.01s")


def _task(tid="T1", status="todo", acceptance="pytest 输出 0 failed", steps=None):
    if steps is None:
        steps = [
            {"title": "先写测试", "status": "done", "touches": ["tests/test_x.py"]},
            {"title": "写实现", "status": "todo", "touches": ["Module/x.py"]},
        ]
    return {
        "id": tid,
        "title": f"任务{tid}",
        "status": status,
        "acceptance": acceptance,
        "steps": steps,
    }


# ============================================================================
# start
# ============================================================================


class TestStart:
    def test_degrades_cleanly_on_empty_root(self, tmp_path, capsys):
        """空目录（无 tasks.json/无 CURRENT_TASK.md/无 AGENTS.md/非 git 目录）→ exit 0 不崩溃"""
        code = session.main(["--root", str(tmp_path), "start"])

        assert code == 0
        out = capsys.readouterr().out
        assert "无当前任务卡" in out
        assert "AGENTS.md 不存在" in out

    def test_default_root_is_cwd(self, tmp_path, monkeypatch, capsys):
        """--root 缺省时使用当前工作目录"""
        monkeypatch.chdir(tmp_path)

        code = session.main(["start"])

        assert code == 0

    def test_agents_md_first_10_lines_preview(self, tmp_path, capsys):
        """AGENTS.md 存在时只预览前 10 行（不输出全文）"""
        lines = [f"第{i}行" for i in range(1, 16)]
        (tmp_path / "AGENTS.md").write_text("\n".join(lines), encoding="utf-8")

        session.main(["--root", str(tmp_path), "start"])

        out = capsys.readouterr().out
        assert "第10行" in out
        assert "第11行" not in out

    def test_prints_first_not_done_task(self, tmp_path, capsys):
        """取第一个 status != done 的任务打印 id/title/status/acceptance/当前步骤"""
        _write_ledger(
            tmp_path,
            [
                _task("T0", status="done"),
                _task("T1", status="in_progress"),
            ],
        )

        session.main(["--root", str(tmp_path), "start"])

        out = capsys.readouterr().out
        assert "id: T1" in out
        assert "title: 任务T1" in out
        assert "status: in_progress" in out
        assert "acceptance: pytest 输出 0 failed" in out
        assert "2. 写实现 [todo]" in out

    def test_all_done_ledger_prints_no_active_task(self, tmp_path, capsys):
        """账本全部 done → 提示无未完成任务"""
        _write_ledger(tmp_path, [_task("T1", status="done")])

        session.main(["--root", str(tmp_path), "start"])

        out = capsys.readouterr().out
        assert "无未完成任务" in out

    def test_incomplete_checklist_warnings(self, tmp_path, capsys):
        """残缺清单：acceptance 为空 + touches 文件缺失 → 警告列出"""
        task = _task(
            "T1",
            acceptance="",
            steps=[
                {"title": "s1", "status": "todo", "touches": ["不存在/missing.py"]},
            ],
        )
        _write_ledger(tmp_path, [task])

        session.main(["--root", str(tmp_path), "start"])

        out = capsys.readouterr().out
        assert "acceptance 为空" in out
        assert "不存在/missing.py" in out

    def test_git_failure_degrades_to_warning(self, tmp_path, capsys):
        """非 git 目录 → git 命令失败降级为警告，仍 exit 0"""
        _write_ledger(tmp_path, [])

        code = session.main(["--root", str(tmp_path), "start"])

        assert code == 0
        out = capsys.readouterr().out
        assert "[警告]" in out


# ============================================================================
# step
# ============================================================================


class TestStep:
    def test_updates_step_status(self, tmp_path):
        """step T1 1 done → tasks.json 中对应步骤状态更新，其余不变"""
        _write_ledger(tmp_path, [_task()])

        code = session.main(["--root", str(tmp_path), "step", "T1", "1", "done"])

        assert code == 0
        ledger = _read_ledger(tmp_path)
        steps = ledger["tasks"][0]["steps"]
        assert steps[0]["status"] == "done"
        assert steps[1]["status"] == "todo"

    def test_back_to_todo(self, tmp_path):
        """step 支持把 done 改回 todo"""
        task = _task()
        task["steps"][0]["status"] = "done"
        _write_ledger(tmp_path, [task])

        code = session.main(["--root", str(tmp_path), "step", "T1", "1", "todo"])

        assert code == 0
        assert _read_ledger(tmp_path)["tasks"][0]["steps"][0]["status"] == "todo"

    def test_current_flag_writes_task_card(self, tmp_path):
        """--current → CURRENT_TASK.md 任务卡（id/title/status/acceptance/steps 快照）"""
        _write_ledger(tmp_path, [_task()])

        code = session.main(
            ["--root", str(tmp_path), "step", "T1", "1", "done", "--current"]
        )

        assert code == 0
        card = (tmp_path / "CURRENT_TASK.md").read_text(encoding="utf-8")
        assert "id: T1" in card
        assert "title: 任务T1" in card
        assert "status: todo" in card
        assert "acceptance: pytest 输出 0 failed" in card
        assert "- [x] 1. 先写测试 (done)" in card
        assert "- [ ] 2. 写实现 (todo)" in card

    def test_unknown_task_returns_1(self, tmp_path, capsys):
        _write_ledger(tmp_path, [_task()])

        code = session.main(["--root", str(tmp_path), "step", "NOPE", "1", "done"])

        assert code == 1
        assert "任务不存在" in capsys.readouterr().err

    def test_step_index_out_of_range_returns_1(self, tmp_path):
        _write_ledger(tmp_path, [_task()])

        assert session.main(["--root", str(tmp_path), "step", "T1", "0", "done"]) == 1
        assert session.main(["--root", str(tmp_path), "step", "T1", "3", "done"]) == 1

    def test_missing_ledger_returns_1(self, tmp_path):
        code = session.main(["--root", str(tmp_path), "step", "T1", "1", "done"])

        assert code == 1

    def test_invalid_status_choice_rejected_by_argparse(self, tmp_path):
        _write_ledger(tmp_path, [_task()])

        with pytest.raises(SystemExit):
            session.main(["--root", str(tmp_path), "step", "T1", "1", "banana"])

        # 账本未被改动
        assert _read_ledger(tmp_path)["tasks"][0]["steps"][0]["status"] == "done"


# ============================================================================
# finish
# ============================================================================


class TestFinish:
    def test_pass_with_green_tests_and_valid_ledger(self, tmp_path, capsys):
        _write_ledger(tmp_path, [_task()])

        code = session.main(["--root", str(tmp_path), "finish"], pytest_runner=_green_runner)

        assert code == 0
        assert "[finish] 通过" in capsys.readouterr().out

    def test_red_tests_returns_1(self, tmp_path, capsys):
        _write_ledger(tmp_path, [_task()])

        code = session.main(["--root", str(tmp_path), "finish"], pytest_runner=_red_runner)

        assert code == 1
        out = capsys.readouterr().out
        assert "pytest 失败" in out
        assert "1 failed, 4 passed" in out  # 输出尾部已打印

    def test_invalid_ledger_returns_1_even_with_green_tests(self, tmp_path):
        """非法 status 值 → 即使测试全绿也 exit 1"""
        task = _task()
        task["steps"][0]["status"] = "banana"
        _write_ledger(tmp_path, [task])

        code = session.main(["--root", str(tmp_path), "finish"], pytest_runner=_green_runner)

        assert code == 1

    def test_unparseable_ledger_returns_1(self, tmp_path, capsys):
        (tmp_path / "tasks.json").write_text("{not json", encoding="utf-8")

        code = session.main(["--root", str(tmp_path), "finish"], pytest_runner=_green_runner)

        assert code == 1
        assert "无法解析" in capsys.readouterr().out

    def test_in_progress_task_blocks_finish(self, tmp_path, capsys):
        """收工门禁：残留 in_progress 任务 → 失败"""
        _write_ledger(tmp_path, [_task(status="in_progress")])

        code = session.main(["--root", str(tmp_path), "finish"], pytest_runner=_red_runner)

        assert code == 1
        out = capsys.readouterr().out
        assert "in_progress" in out

    def test_missing_ledger_fails(self, tmp_path):
        code = session.main(["--root", str(tmp_path), "finish"], pytest_runner=_green_runner)

        assert code == 1

    def test_empty_ledger_passes(self, tmp_path):
        """空账本 {"tasks": []} → 通过（基线状态可收工）"""
        _write_ledger(tmp_path, [])

        code = session.main(["--root", str(tmp_path), "finish"], pytest_runner=_green_runner)

        assert code == 0


# ============================================================================
# verify
# ============================================================================


class TestVerify:
    def test_pass_with_green_tests_and_valid_ledger(self, tmp_path, capsys):
        _write_ledger(tmp_path, [])

        code = session.main(["--root", str(tmp_path), "verify"], pytest_runner=_green_runner)

        assert code == 0
        assert "[verify] 通过" in capsys.readouterr().out

    def test_ignores_task_status(self, tmp_path, capsys):
        """verify 与 finish 的差异：不检查任务状态（in_progress 不拦截）"""
        _write_ledger(tmp_path, [_task(status="in_progress")])

        code = session.main(["--root", str(tmp_path), "verify"], pytest_runner=_green_runner)

        assert code == 0
        assert "[verify] 通过" in capsys.readouterr().out

    def test_invalid_ledger_returns_1(self, tmp_path):
        task = _task()
        task["status"] = "banana"
        _write_ledger(tmp_path, [task])

        code = session.main(["--root", str(tmp_path), "verify"], pytest_runner=_green_runner)

        assert code == 1

    def test_red_tests_returns_1(self, tmp_path):
        _write_ledger(tmp_path, [])

        code = session.main(["--root", str(tmp_path), "verify"], pytest_runner=_red_runner)

        assert code == 1


# ============================================================================
# new-adr
# ============================================================================


class TestNewAdr:
    def test_creates_first_adr_with_template(self, tmp_path):
        code = session.main(["--root", str(tmp_path), "new-adr", "采用会话账本"])

        assert code == 0
        path = tmp_path / "docs" / "adr" / "0001-采用会话账本.md"
        assert path.exists()
        content = path.read_text(encoding="utf-8")
        # 模板四节 + 状态默认"提议"
        for section in ("## 状态", "## 背景", "## 决策", "## 后果"):
            assert section in content
        assert "提议" in content
        assert "# ADR-0001: 采用会话账本" in content

    def test_number_auto_increments(self, tmp_path):
        adr_dir = tmp_path / "docs" / "adr"
        adr_dir.mkdir(parents=True)
        (adr_dir / "0001-旧决策.md").write_text("x", encoding="utf-8")
        (adr_dir / "0005-最高.md").write_text("x", encoding="utf-8")

        code = session.main(["--root", str(tmp_path), "new-adr", "新决策"])

        assert code == 0
        assert (adr_dir / "0006-新决策.md").exists()

    def test_creates_adr_dir_if_missing(self, tmp_path):
        """docs/adr 目录不存在时自动创建"""
        code = session.main(["--root", str(tmp_path), "new-adr", "首篇"])

        assert code == 0
        assert (tmp_path / "docs" / "adr" / "0001-首篇.md").exists()

    def test_filename_sanitized(self, tmp_path):
        """标题中的文件名非法字符被替换"""
        code = session.main(["--root", str(tmp_path), "new-adr", "a/b:c*d?"])

        assert code == 0
        created = list((tmp_path / "docs" / "adr").glob("0001-*.md"))
        assert len(created) == 1
        assert ":" not in created[0].name
        assert "?" not in created[0].name
        assert created[0].name == "0001-a-b-c-d-.md"
