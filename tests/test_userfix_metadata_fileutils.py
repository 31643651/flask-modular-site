"""
userfix metadata.json 走 file_utils 线程安全函数测试（bug #26）

- update_submission_status：写后读回一致（其余字段不丢失）
- metadata.json 损坏时按 file_utils 语义处理：更新返回失败不崩溃、列表跳过该记录
"""

import json

import pytest

from Module.core.userfix_service import UserfixService


VALID_ID = "alice_2026-01-01_00-00-00_000000"


def _make_submission(root, submission_id, metadata=None, content="hello"):
    """在临时提交目录内创建一条提交记录（metadata.json + content.txt）"""
    sub_dir = root / submission_id
    sub_dir.mkdir(parents=True, exist_ok=True)
    (sub_dir / "metadata.json").write_text(
        json.dumps(metadata or {"username": "alice", "images": []}, ensure_ascii=False),
        encoding="utf-8",
    )
    (sub_dir / "content.txt").write_text(content, encoding="utf-8")
    return sub_dir


@pytest.fixture
def submissions_root(tmp_path, monkeypatch):
    """将 admin_service 的提交目录重定向到临时目录，避免触碰生产数据"""
    root = tmp_path / "submissions"
    root.mkdir()
    monkeypatch.setattr("Module.core.userfix_service.USERFIX_SUBMISSIONS_DIR", root)
    return root


@pytest.fixture
def config_file(tmp_path, monkeypatch):
    """将 config.json 重定向到临时文件，避免读生产配置"""
    target = tmp_path / "config.json"
    monkeypatch.setattr("Module.common.config_utils.CONFIG_FILE", target)
    return target


class TestUpdateStatusRoundtrip:
    """更新状态后 metadata 写后读回一致（走 file_utils）"""

    def test_update_preserves_other_fields(self, submissions_root, config_file):
        """状态更新生效且其余字段不丢失（写后读回一致）"""
        metadata = {
            "username": "alice",
            "timestamp": "2026-01-01T00:00:00",
            "images": ["shot.png"],
            "status": "unprocessed",
        }
        _make_submission(submissions_root, VALID_ID, metadata=metadata)

        success, message = UserfixService().update_submission_status(
            VALID_ID, "processed"
        )
        assert success is True
        assert message == "状态更新成功"

        read_back = json.loads(
            (submissions_root / VALID_ID / "metadata.json").read_text(
                encoding="utf-8"
            )
        )
        assert read_back["status"] == "processed"
        assert read_back["username"] == "alice"
        assert read_back["timestamp"] == "2026-01-01T00:00:00"
        assert read_back["images"] == ["shot.png"]


class TestCorruptMetadataHandledByFileUtils:
    """metadata.json 损坏时按 file_utils 语义处理（default 哨兵），不崩溃"""

    def test_update_corrupt_metadata_fails_cleanly(
        self, submissions_root, config_file
    ):
        """损坏文件：更新返回失败且带可读信息，不抛异常"""
        sub_dir = submissions_root / VALID_ID
        sub_dir.mkdir(parents=True)
        (sub_dir / "metadata.json").write_text("not-json{{{", encoding="utf-8")

        success, message = UserfixService().update_submission_status(
            VALID_ID, "processed"
        )
        assert success is False
        assert "损坏" in message or "失败" in message

    def test_listing_skips_corrupt_metadata(
        self, submissions_root, config_file
    ):
        """列表：损坏记录被跳过，合法记录正常返回（既有跳过语义不回归）"""
        _make_submission(
            submissions_root,
            "bob_2026-01-02_00-00-00_000000",
            metadata={"username": "bob", "status": "processed"},
        )
        # 损坏记录
        bad_dir = submissions_root / VALID_ID
        bad_dir.mkdir(parents=True)
        (bad_dir / "metadata.json").write_text("not-json{{{", encoding="utf-8")

        submissions = UserfixService().list_submissions()
        ids = [s["id"] for s in submissions]
        assert ids == ["bob_2026-01-02_00-00-00_000000"]

    def test_missing_metadata_file_skipped(self, submissions_root, config_file):
        """无 metadata.json 的目录仍被跳过（存在性检查语义不回归）"""
        (submissions_root / "empty_dir").mkdir()
        _make_submission(
            submissions_root,
            "bob_2026-01-02_00-00-00_000000",
            metadata={"username": "bob"},
        )

        submissions = UserfixService().list_submissions()
        assert [s["id"] for s in submissions] == [
            "bob_2026-01-02_00-00-00_000000"
        ]
