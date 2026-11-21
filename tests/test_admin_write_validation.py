"""
挂载/配置写入侧校验恢复测试（ADR-0006 根因 B）

背景：历史安全修复 be033be(H1)、a4713d4(H13)、aff91cf(S4)、dcdcdc9(M39)
写在 Module/admin/admin.py，该文件在 f79b372 模块化重构中被拆分删除，
校验未迁移到 Module/core/admin_service.py，导致：

- add_mounted_page：无名称格式/路径存在性/系统敏感路径/HTML-only/上限/重名校验
- update_config：current.update(new_config) 裸合并，任意顶层键可写入
- remove_mounted_page：对不存在的名称恒返回成功
"""

import json
from pathlib import Path

import pytest

from Module.core.admin_service import AdminService

CSRF_TOKEN = "test-csrf-token"
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def config_file(tmp_path, monkeypatch):
    """将 config.json 重定向到临时文件，避免写生产配置"""
    target = tmp_path / "config.json"
    monkeypatch.setattr("Module.common.config_utils.CONFIG_FILE", target)
    return target


@pytest.fixture
def service(config_file):
    return AdminService()


def _login_superadmin(client):
    from Module.common import user_utils

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


# ============================================================================
# add_mounted_page 校验（恢复 a4713d4 H13 + 历史名称/存在性/HTML/上限/重名）
# ============================================================================


class TestAddMountedPageValidation:
    def test_rejects_bad_name_format(self, service):
        """名称只允许 ASCII 字母/数字/下划线/短横线（历史正则）"""
        for bad in ["中文名", "has space", "a/b", "a.b", ""]:
            success, message = service.add_mounted_page(bad, "sdinspector")
            assert success is False, f"非法名称 {bad!r} 应被拒绝"
            assert message

    def test_rejects_nonexistent_path(self, service):
        """路径不存在时拒绝（M39 口径，add 侧历史校验）"""
        success, message = service.add_mounted_page(
            "ghost", "no_such_dir_or_file_xyz"
        )
        assert success is False
        assert "不存在" in message

    def test_rejects_sensitive_system_path(self, service):
        """系统敏感路径白名单：禁止挂载（a4713d4 H13）"""
        import os

        windows = Path(os.environ.get("SystemRoot", "C:/Windows"))
        if not windows.exists():
            pytest.skip("无 Windows 系统目录")
        success, message = service.add_mounted_page("winsys", str(windows))
        assert success is False
        assert "敏感" in message

    def test_rejects_non_html_file(self, service):
        """文件挂载仅支持 HTML 文件（历史校验）"""
        target = ROOT / "requirements.txt"
        if not target.exists():
            pytest.skip("requirements.txt 不存在")
        success, message = service.add_mounted_page("reqs", str(target))
        assert success is False
        assert "HTML" in message

    def test_accepts_existing_html_file(self, service):
        """真实存在的 HTML 文件可挂载（正向锚定）"""
        target = ROOT / "sdinspector" / "index.html"
        if not target.exists():
            pytest.skip("sdinspector/index.html 不存在")
        success, message = service.add_mounted_page("sdi", str(target))
        assert success is True, message

    def test_rejects_duplicate_name(self, service):
        """重名拒绝（历史校验）"""
        target = ROOT / "sdinspector" / "index.html"
        if not target.exists():
            pytest.skip("sdinspector/index.html 不存在")
        success, _ = service.add_mounted_page("dup", str(target))
        assert success is True
        success, message = service.add_mounted_page("dup", str(target))
        assert success is False
        assert "已存在" in message

    def test_rejects_over_limit(self, service, config_file):
        """挂载数量上限 20（历史校验）"""
        target = ROOT / "sdinspector" / "index.html"
        if not target.exists():
            pytest.skip("sdinspector/index.html 不存在")
        pages = [
            {"name": f"p{i}", "path": str(target), "type": "file"} for i in range(20)
        ]
        config_file.write_text(
            json.dumps({"mounted_pages": pages}), encoding="utf-8"
        )
        success, message = service.add_mounted_page("one-more", str(target))
        assert success is False
        assert "上限" in message


# ============================================================================
# remove_mounted_page：不存在判定（历史 admin.py 行为）
# ============================================================================


class TestRemoveMountedPageNotFound:
    def test_remove_missing_page_fails(self, service, config_file):
        """删除不存在的页面返回失败（历史行为；当前实现恒成功是缺陷）"""
        config_file.write_text(json.dumps({"mounted_pages": []}), encoding="utf-8")
        success, message = service.remove_mounted_page("nope")
        assert success is False
        assert "不存在" in message

    def test_remove_existing_page_succeeds(self, service, config_file):
        config_file.write_text(
            json.dumps(
                {"mounted_pages": [{"name": "gone", "path": "x", "type": "file"}]}
            ),
            encoding="utf-8",
        )
        success, message = service.remove_mounted_page("gone")
        assert success is True
        on_disk = json.loads(config_file.read_text(encoding="utf-8"))
        assert on_disk["mounted_pages"] == []


# ============================================================================
# update_config 白名单与路径校验（恢复 aff91cf S4 + dcdcdc9 M39 + 键白名单）
# ============================================================================


class TestUpdateConfigValidation:
    def test_rejects_unknown_top_level_key(self, service):
        """顶层键白名单：任意键不再能裸合并进 config"""
        success, message = service.update_config({"evil_key": 1})
        assert success is False

    def test_rejects_unknown_paths_key(self, service):
        success, message = service.update_config({"paths": {"evil": "x"}})
        assert success is False

    def test_rejects_empty_path(self, service):
        """S4：路径空值/null 拒绝"""
        for bad in ["", "   ", None]:
            success, message = service.update_config(
                {"paths": {"book_data_path": bad}}
            )
            assert success is False, f"空路径 {bad!r} 应被拒绝"

    def test_rejects_non_string_path(self, service):
        success, message = service.update_config(
            {"paths": {"book_data_path": 123}}
        )
        assert success is False

    def test_rejects_nonexistent_path(self, service):
        """M39：路径存在性校验"""
        success, message = service.update_config(
            {"paths": {"book_data_path": "no_such_dir_xyz/"}}
        )
        assert success is False
        assert "不存在" in message

    def test_accepts_existing_path(self, service, config_file):
        """正向：真实存在的目录可保存，且不破坏其他既有键"""
        config_file.write_text(
            json.dumps({"paths": {"gallery_root_path": "old_value"}}),
            encoding="utf-8",
        )
        target = ROOT / "sdinspector"
        if not target.exists():
            pytest.skip("sdinspector 不存在")
        success, message = service.update_config(
            {"paths": {"book_data_path": str(target)}}
        )
        assert success is True, message
        on_disk = json.loads(config_file.read_text(encoding="utf-8"))
        assert on_disk["paths"]["book_data_path"] == str(target)
        # 既有键保留（裸 update 会整体替换 paths 的反例由下一条锚定）
        assert on_disk["paths"]["gallery_root_path"] == "old_value"

    def test_rejects_non_bool_wallpaper_enabled(self, service):
        success, message = service.update_config(
            {"wallpaper": {"enabled": "yes"}}
        )
        assert success is False

    def test_rejects_non_list_mounted_pages(self, service):
        success, message = service.update_config({"mounted_pages": {}})
        assert success is False

    def test_rejects_over_limit_mounted_pages(self, service):
        pages = [{"name": f"p{i}", "path": "x", "type": "file"} for i in range(21)]
        success, message = service.update_config({"mounted_pages": pages})
        assert success is False


# ============================================================================
# 路由层失败响应口径：{success, message}，不携带跳转字段（B5 契约）
# ============================================================================


class TestRouteFailureShape:
    def test_add_failure_response_shape(self, client, app, config_file):
        _login_superadmin(client)
        resp = client.post(
            "/admin/mounted-pages",
            json={"name": "ghost", "path": "no_such_path_xyz"},
            headers=_csrf_headers(),
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is False
        assert "message" in data
        assert "redirect_url" not in data
        assert "name" not in data
        assert "page_type" not in data

    def test_delete_missing_page_reports_failure(self, client, app, config_file):
        """删除不存在的挂载页面：前端应收到失败（历史行为）"""
        _login_superadmin(client)
        config_file.write_text(json.dumps({"mounted_pages": []}), encoding="utf-8")
        resp = client.delete(
            "/admin/mounted-pages/ghost", headers=_csrf_headers()
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is False
        assert "不存在" in data["message"]

    def test_config_update_rejects_unknown_key(self, client, app, config_file):
        _login_superadmin(client)
        resp = client.post(
            "/admin/config/update",
            json={"evil_key": 1},
            headers=_csrf_headers(),
        )
        data = resp.get_json()
        assert data["success"] is False


# ============================================================================
# config.html：禁用输入框不提交空串（配合恢复的 S4 空值校验，ADR-0006）
# ============================================================================


class TestSaveConfigDisabledFields:
    TEMPLATE = ROOT / "Module/admin/templates/admin/config.html"

    def test_save_config_omits_disabled_fields(self):
        """saveConfig 不得对禁用字段提交 ''（会被 S4 空值校验整单拒绝）"""
        source = self.TEMPLATE.read_text(encoding="utf-8")
        import re

        m = re.search(r"function saveConfig\(\)\s*\{([\s\S]*?)\n        \}", source)
        assert m, "config.html 缺少 saveConfig 函数"
        body = m.group(1)
        assert "disabled ? ''" not in body, (
            "saveConfig 不得把禁用输入框提交为空串（会被路径空值校验拒绝）"
        )
        assert "input.disabled" in body or "!input.disabled" in body, (
            "saveConfig 应跳过禁用的路径输入框"
        )
