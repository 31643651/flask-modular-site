"""
userfix 管理接口路径穿越校验测试（bug #17）：

- 服务层入口正则校验：[A-Za-z0-9_-]+ 之外的一切（../、/、\\、空串、非字符串）被拒
- 防御纵深：resolve + relative_to 双保险
- 注入请求不产生任何文件系统副作用（目录内容不变、外部目标不被删除/写入）
- 合法 ID 正常走通（更新状态 / 删除）
- API 层真实链路：test client + CSRF + 超级管理员会话
"""

import pytest

from Module.common import user_utils
from Module.core.userfix_service import UserfixService

CSRF_TOKEN = "test-csrf-token"

VALID_ID = "alice_2026-01-01_00-00-00_000000"

# 注入样本：应被服务层校验拒绝（相对穿越、内嵌穿越、含分隔符、空串、点、反斜杠）
EVIL_IDS = [
    "../evil",
    "a/../b",
    "../../outside",
    "sub/dir",
    "a/b",
    "a\\b",
    "..\\evil",
    ".",
    "..",
    "",
    " ",
    "id\n",
    "a.b",
    "张三/../evil",
    "张三\\evil",
]


def _make_submission(root, submission_id, status="unprocessed"):
    """在临时提交目录内创建一条真实提交记录（metadata.json + content.txt）"""
    sub_dir = root / submission_id
    sub_dir.mkdir(parents=True)
    (sub_dir / "metadata.json").write_text(
        '{"username": "alice", "timestamp": "2026-01-01T00:00:00", '
        '"images": [], "status": "' + status + '"}',
        encoding="utf-8",
    )
    (sub_dir / "content.txt").write_text("hello", encoding="utf-8")
    return sub_dir


def _snapshot_dir(path):
    """快照目录结构（相对路径 + 文件大小），用于断言无副作用"""
    entries = {}
    for p in sorted(path.rglob("*")):
        key = str(p.relative_to(path))
        entries[key] = p.stat().st_size if p.is_file() else "<dir>"
    return entries


@pytest.fixture
def submissions_root(tmp_path, monkeypatch):
    """将 admin_service 的提交目录重定向到临时目录，避免触碰生产数据"""
    root = tmp_path / "submissions"
    root.mkdir()
    monkeypatch.setattr(
        "Module.core.userfix_service.USERFIX_SUBMISSIONS_DIR", root
    )
    return root


@pytest.fixture
def config_file(tmp_path, monkeypatch):
    """将 config.json 重定向到临时文件，避免读生产配置"""
    target = tmp_path / "config.json"
    monkeypatch.setattr("Module.common.config_utils.CONFIG_FILE", target)
    return target


@pytest.fixture
def seeded_root(submissions_root):
    """已含一条合法提交记录 + 一个外部哨兵目录的临时提交目录"""
    _make_submission(submissions_root, VALID_ID)
    # 提交目录之外的哨兵：../evil 穿越的目标，删除成功即说明校验失效
    outside = submissions_root.parent / "evil"
    outside.mkdir()
    outside.joinpath("marker.txt").write_text("do-not-delete", encoding="utf-8")
    return submissions_root


class TestServiceLayerPathTraversal:
    """服务层入口校验（防御必须放在服务层，覆盖所有调用方）"""

    @pytest.mark.parametrize("evil_id", EVIL_IDS)
    def test_update_status_rejects_traversal_no_side_effects(
        self, seeded_root, evil_id
    ):
        """非法 ID 更新状态被拒且不产生任何文件系统副作用"""
        service = UserfixService()
        before = _snapshot_dir(seeded_root)

        success, message = service.update_submission_status(evil_id, "processed")

        assert success is False
        assert "非法" in message
        assert _snapshot_dir(seeded_root) == before
        # 外部穿越目标未被写入 metadata.json
        if evil_id == "../evil":
            assert not (seeded_root.parent / "evil" / "metadata.json").exists()

    @pytest.mark.parametrize("evil_id", EVIL_IDS)
    def test_delete_rejects_traversal_no_side_effects(self, seeded_root, evil_id):
        """非法 ID 删除被拒且不产生任何文件系统副作用"""
        service = UserfixService()
        before = _snapshot_dir(seeded_root)

        success, message = service.delete_submission(evil_id)

        assert success is False
        assert "非法" in message
        assert _snapshot_dir(seeded_root) == before
        # 外部穿越目标仍然完整存在（rmtree 未被触达）
        assert (seeded_root.parent / "evil" / "marker.txt").exists()

    def test_delete_traversal_target_outside_root_survives(
        self, tmp_path, monkeypatch
    ):
        """../evil 穿越时，目录树外的真实目标不被删除"""
        root = tmp_path / "submissions"
        root.mkdir()
        monkeypatch.setattr(
            "Module.core.userfix_service.USERFIX_SUBMISSIONS_DIR", root
        )
        target = tmp_path / "evil"
        target.mkdir()
        (target / "precious.txt").write_text("x", encoding="utf-8")

        success, _ = UserfixService().delete_submission("../evil")

        assert success is False
        assert target.is_dir()
        assert (target / "precious.txt").exists()

    def test_non_string_id_rejected(self, seeded_root):
        """非字符串 ID（如数字）同样被正则层拒绝，不抛异常"""
        service = UserfixService()
        before = _snapshot_dir(seeded_root)

        assert service.update_submission_status(123, "processed") == (
            False,
            "非法的提交记录 ID",
        )
        assert service.delete_submission(None) == (False, "非法的提交记录 ID")
        assert _snapshot_dir(seeded_root) == before

    def test_update_status_valid_id_works(self, seeded_root):
        """合法 ID 更新状态正常生效"""
        success, message = UserfixService().update_submission_status(
            VALID_ID, "processed"
        )
        assert success is True
        assert message == "状态更新成功"
        metadata_file = seeded_root / VALID_ID / "metadata.json"
        assert '"status": "processed"' in metadata_file.read_text(encoding="utf-8")

    def test_delete_valid_id_works(self, seeded_root):
        """合法 ID 删除正常生效，其余记录不受影响"""
        _make_submission(seeded_root, "bob_2026-01-02_00-00-00_000000")

        success, message = UserfixService().delete_submission(VALID_ID)

        assert success is True
        assert message == "删除成功"
        assert not (seeded_root / VALID_ID).exists()
        assert (seeded_root / "bob_2026-01-02_00-00-00_000000").exists()

    def test_nonexistent_but_legal_id_rejected(self, seeded_root):
        """格式合法但记录不存在的 ID 返回记录不存在（不误报为非法）"""
        success, message = UserfixService().delete_submission(
            "bob_2026-01-02_00-00-00_000000"
        )
        assert success is False
        assert "不存在" in message

    # --- 非 ASCII 目录名兼容（修复轮 1，bug #17 规格调整）---

    NON_ASCII_ID = "张三_2026-01-01_00-00-00_000000"

    def test_update_status_non_ascii_id_works(self, seeded_root):
        """中文用户名的真实目录名可正常更新状态（不再被 ASCII 白名单误杀）"""
        _make_submission(seeded_root, self.NON_ASCII_ID)

        success, message = UserfixService().update_submission_status(
            self.NON_ASCII_ID, "processed"
        )

        assert success is True
        assert message == "状态更新成功"
        metadata_file = seeded_root / self.NON_ASCII_ID / "metadata.json"
        assert '"status": "processed"' in metadata_file.read_text(encoding="utf-8")

    def test_delete_non_ascii_id_works(self, seeded_root):
        """中文用户名的真实目录名可正常删除，其余记录不受影响"""
        _make_submission(seeded_root, self.NON_ASCII_ID)

        success, message = UserfixService().delete_submission(self.NON_ASCII_ID)

        assert success is True
        assert message == "删除成功"
        assert not (seeded_root / self.NON_ASCII_ID).exists()
        assert (seeded_root / VALID_ID).exists()

    def test_french_accented_id_works(self, seeded_root):
        """带变音符的拉丁用户名（Unicode isalnum 白名单形态）同样兼容"""
        accented_id = "français_2026-01-01_00-00-00_000000"
        _make_submission(seeded_root, accented_id)

        success, message = UserfixService().update_submission_status(
            accented_id, "processed"
        )

        assert success is True
        assert "状态更新成功" in message


class TestApiLayerPathTraversal:
    """API 层真实链路：test client + CSRF + 超级管理员会话"""

    def _login_superadmin(self, client):
        users = {
            "admin": {
                "id": 0,
                "username": "admin",
                "password": "p",
                "role": "admin",
                "enabled": True,
                "is_superadmin": True,
            }
        }
        user_utils.save_users(users)
        with client.session_transaction() as sess:
            sess["user_id"] = 0
            sess["username"] = "admin"
            sess["role"] = "admin"
            sess["verified"] = True
            sess["csrf_token"] = CSRF_TOKEN

    def _csrf_headers(self):
        return {"X-CSRF-Token": CSRF_TOKEN}

    def test_api_update_status_rejects_traversal(
        self, client, app, config_file, seeded_root
    ):
        """API 层 ../evil 更新状态被拒，且无任何文件系统副作用"""
        self._login_superadmin(client)
        before = _snapshot_dir(seeded_root)

        resp = client.post(
            "/admin/userfix/api/update-status",
            json={"id": "../evil", "status": "processed"},
            headers=self._csrf_headers(),
        )

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is False
        assert _snapshot_dir(seeded_root) == before
        assert not (seeded_root.parent / "evil" / "metadata.json").exists()

    def test_api_delete_rejects_traversal(self, client, app, config_file, seeded_root):
        """API 层 ../evil 删除被拒，外部目标不被删除"""
        self._login_superadmin(client)
        before = _snapshot_dir(seeded_root)

        resp = client.post(
            "/admin/userfix/api/delete",
            json={"id": "../evil"},
            headers=self._csrf_headers(),
        )

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is False
        assert _snapshot_dir(seeded_root) == before
        assert (seeded_root.parent / "evil" / "marker.txt").exists()

    def test_api_update_status_valid_id_works(
        self, client, app, config_file, seeded_root
    ):
        """API 层合法 ID 更新状态正常走通"""
        self._login_superadmin(client)

        resp = client.post(
            "/admin/userfix/api/update-status",
            json={"id": VALID_ID, "status": "resolved"},
            headers=self._csrf_headers(),
        )

        assert resp.status_code == 200
        assert resp.get_json()["success"] is True
        assert "resolved" in (
            (seeded_root / VALID_ID / "metadata.json").read_text(encoding="utf-8")
        )

    def test_api_update_status_non_ascii_id_end_to_end(
        self, client, app, config_file, seeded_root
    ):
        """API 层端到端：中文用户名目录名的状态更新真实链路走通"""
        self._login_superadmin(client)
        non_ascii_id = "张三_2026-01-01_00-00-00_000000"
        _make_submission(seeded_root, non_ascii_id)

        resp = client.post(
            "/admin/userfix/api/update-status",
            json={"id": non_ascii_id, "status": "resolved"},
            headers=self._csrf_headers(),
        )

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert "resolved" in (
            (seeded_root / non_ascii_id / "metadata.json").read_text(encoding="utf-8")
        )

    def test_api_delete_non_ascii_id_end_to_end(
        self, client, app, config_file, seeded_root
    ):
        """API 层端到端：中文用户名目录名可正常删除"""
        self._login_superadmin(client)
        non_ascii_id = "张三_2026-01-01_00-00-00_000000"
        _make_submission(seeded_root, non_ascii_id)

        resp = client.post(
            "/admin/userfix/api/delete",
            json={"id": non_ascii_id},
            headers=self._csrf_headers(),
        )

        assert resp.status_code == 200
        assert resp.get_json()["success"] is True
        assert not (seeded_root / non_ascii_id).exists()
