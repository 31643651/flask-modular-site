"""
admin 挂载页面 API 测试（bug #11 + #12）：

- #11 添加接口成功响应含 name/page_type/redirect_url
- #12 列表 API 返回 {name, path, type} 结构（防止回归成 is_file 形态）
- config.html 模板级断言（不再引用 page.is_file、type 判断存在、created_at 缺失分支存在）
"""

import json
from pathlib import Path

import pytest

from Module.common import user_utils

CSRF_TOKEN = "test-csrf-token"

TEMPLATE_PATH = (
    Path(__file__).resolve().parents[1] / "Module/admin/templates/admin/config.html"
)


@pytest.fixture
def config_file(tmp_path, monkeypatch):
    """将 config.json 重定向到临时文件，避免写生产配置"""
    target = tmp_path / "config.json"
    monkeypatch.setattr("Module.common.config_utils.CONFIG_FILE", target)
    return target


def _login_superadmin(client):
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


def _csrf_headers():
    return {"X-CSRF-Token": CSRF_TOKEN}


class TestAddMountedPageResponse:
    """添加挂载接口成功响应字段（bug #11 主修复）"""

    def test_success_response_contains_name_page_type_redirect_url(
        self, client, app, config_file
    ):
        """成功响应含 name/page_type/redirect_url 且值正确"""
        _login_superadmin(client)
        resp = client.post(
            "/admin/mounted-pages",
            json={"name": "docs", "path": "sdinspector/index.html"},
            headers=_csrf_headers(),
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["name"] == "docs"
        assert data["page_type"] == "file"
        assert data["redirect_url"] == "/docs"

    def test_directory_type_echoed(self, client, app, config_file):
        """显式传 type=directory 时 page_type 回显真实判断值"""
        _login_superadmin(client)
        resp = client.post(
            "/admin/mounted-pages",
            json={"name": "static", "path": "sdinspector", "type": "directory"},
            headers=_csrf_headers(),
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["page_type"] == "directory"
        assert data["redirect_url"] == "/static"

    def test_failure_response_has_no_redirect_fields(self, client, app, config_file):
        """失败响应仍为 {success, message}，不携带跳转字段"""
        _login_superadmin(client)
        resp = client.post(
            "/admin/mounted-pages",
            json={"name": "", "path": "sdinspector/index.html"},
            headers=_csrf_headers(),
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is False
        assert "redirect_url" not in data
        assert "page_type" not in data

    def test_added_page_persisted_with_type(self, client, app, config_file):
        """添加结果持久化为 {name, path, type}，存储结构不含 created_at"""
        _login_superadmin(client)
        client.post(
            "/admin/mounted-pages",
            json={"name": "docs", "path": "sdinspector/index.html"},
            headers=_csrf_headers(),
        )
        on_disk = json.loads(config_file.read_text(encoding="utf-8"))
        assert on_disk["mounted_pages"] == [
            {"name": "docs", "path": "sdinspector/index.html", "type": "file"}
        ]


class TestListMountedPages:
    """列表 API 结构（bug #12 回归防护）"""

    def test_list_returns_name_path_type(self, client, app, config_file):
        """列表 API 每项精确为 {name, path, type}，无 is_file/created_at"""
        _login_superadmin(client)
        client.post(
            "/admin/mounted-pages",
            json={"name": "docs", "path": "sdinspector/index.html"},
            headers=_csrf_headers(),
        )
        resp = client.get("/admin/mounted-pages")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert len(data["pages"]) == 1
        page = data["pages"][0]
        assert set(page.keys()) == {"name", "path", "type"}
        assert page["name"] == "docs"
        assert page["path"] == "sdinspector/index.html"
        assert page["type"] == "file"
        assert "is_file" not in page
        assert "created_at" not in page

    def test_list_requires_superadmin(self, client, app, config_file):
        """未登录 GET 被重定向到登录页（既有行为）"""
        resp = client.get("/admin/mounted-pages")
        assert resp.status_code == 302
        assert "login" in resp.location


class TestLegacyFormatFallback:
    """旧格式记录（缺 type / 只有 is_file）的回退推断（I4）"""

    def _write_config(self, config_file, pages):
        config_file.write_text(
            json.dumps({"mounted_pages": pages}, ensure_ascii=False),
            encoding="utf-8",
        )

    def test_legacy_record_with_type_kept_as_is(self, client, app, config_file):
        """有 type 键的记录原样保留，推断不改变其值"""
        _login_superadmin(client)
        self._write_config(
            config_file,
            [{"name": "docs", "path": "D:/test/page.html", "type": "directory"}],
        )

        resp = client.get("/admin/mounted-pages")

        data = resp.get_json()
        assert data["success"] is True
        assert data["pages"][0]["type"] == "directory"

    def test_legacy_records_with_is_file_inferred(self, client, app, config_file):
        """只有 is_file 的记录：True→file、False→directory，返回结构仍为 {name, path, type}"""
        _login_superadmin(client)
        self._write_config(
            config_file,
            [
                {"name": "a", "path": "D:/test/a.html", "is_file": True},
                {"name": "b", "path": "D:/test/b/", "is_file": False},
            ],
        )

        resp = client.get("/admin/mounted-pages")

        data = resp.get_json()
        pages = data["pages"]
        assert pages[0]["type"] == "file"
        assert pages[1]["type"] == "directory"
        # 回退推断后返回结构仍符合 spec 的 {name, path, type}（is_file 不外露）
        for page in pages:
            assert set(page.keys()) == {"name", "path", "type"}

    def test_legacy_record_without_either_defaults_file(self, client, app, config_file):
        """type 与 is_file 都无的记录默认推断为 file（与 index.py 缺省倾向文件口径一致）"""
        _login_superadmin(client)
        self._write_config(
            config_file,
            [{"name": "legacy", "path": "D:/test/legacy.html"}],
        )

        resp = client.get("/admin/mounted-pages")

        page = resp.get_json()["pages"][0]
        assert page["type"] == "file"
        assert set(page.keys()) == {"name", "path", "type"}

    def test_mixed_records_all_normalized(self, client, app, config_file):
        """混合列表：新格式 / 含 type / 含 is_file / 都无 → 各自正确的 type"""
        _login_superadmin(client)
        self._write_config(
            config_file,
            [
                {"name": "new", "path": "D:/test/n.html", "type": "file"},
                {"name": "withtype", "path": "D:/test/w/", "type": "directory"},
                {"name": "isfile1", "path": "D:/test/f.html", "is_file": True},
                {"name": "isfile0", "path": "D:/test/g/", "is_file": False},
                {"name": "bare", "path": "D:/test/b.html"},
            ],
        )

        resp = client.get("/admin/mounted-pages")

        types = {p["name"]: p["type"] for p in resp.get_json()["pages"]}
        assert types == {
            "new": "file",
            "withtype": "directory",
            "isfile1": "file",
            "isfile0": "directory",
            "bare": "file",
        }

    def test_normalization_not_persisted(self, client, app, config_file):
        """规范化只作用于返回值：config.json 磁盘内容保持旧格式原样"""
        _login_superadmin(client)
        legacy = [{"name": "docs", "path": "D:/test/page.html", "is_file": True}]
        self._write_config(config_file, legacy)

        client.get("/admin/mounted-pages")

        on_disk = json.loads(config_file.read_text(encoding="utf-8"))
        assert on_disk["mounted_pages"] == legacy


class TestTemplateAlignment:
    """config.html 模板级断言（bug #12 前端修复）"""

    def _html(self):
        return TEMPLATE_PATH.read_text(encoding="utf-8")

    def test_no_is_file_reference(self):
        """模板不再引用 page.is_file"""
        html = self._html()
        assert "page.is_file" not in html

    def test_type_check_present(self):
        """类型列改用 page.type === 'file' 判断"""
        assert "page.type === 'file'" in self._html()

    def test_created_at_missing_branch_present(self):
        """created_at 缺失分支存在且显示占位符"""
        html = self._html()
        assert "page.created_at ?" in html
        assert ": '—'" in html

    def test_add_success_consumes_new_fields(self):
        """添加成功分支消费 data.name/page_type/redirect_url"""
        html = self._html()
        assert "data.page_type" in html
        assert "data.name" in html
        assert "data.redirect_url" in html
