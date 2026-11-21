"""
画廊偏好设置测试：保存结构（包裹形态/裸字典）、读回、服务端渲染初始偏好
"""

import json
import re

import pytest

from Module.common import user_utils


CSRF_TOKEN = "test-csrf-token"


@pytest.fixture
def prefs_file(tmp_path, monkeypatch):
    """将画廊偏好 JSON 重定向到临时文件，避免写生产 gallery_preferences.json"""
    target = tmp_path / "gallery_preferences.json"
    monkeypatch.setattr("Module.core.gallery_service.PREFERENCES_FILE", target)
    return target


def _login(client, app, username="alice"):
    """创建用户并注入登录态与 CSRF token"""
    user_utils.save_users(
        {
            username: {
                "id": 1,
                "username": username,
                "password": "pass123",
                "role": "user",
                "enabled": True,
            },
        }
    )
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["username"] = username
        sess["role"] = "user"
        sess["verified"] = True
        sess["csrf_token"] = CSRF_TOKEN


def _post_prefs(client, payload):
    return client.post(
        "/gallery/api/preferences",
        json=payload,
        headers={"X-CSRF-Token": CSRF_TOKEN},
    )


def _get_prefs(client):
    resp = client.get("/gallery/api/preferences")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    return data["preferences"]


class TestSaveAndReadBack:
    """保存偏好（两种形态）后读回应返回保存值而非默认值"""

    def test_wrapped_form_saved_and_read_back(self, client, app, prefs_file):
        """preferences 包裹形态：保存后读回为保存值（bug #6 主修复）"""
        _login(client, app)
        resp = _post_prefs(
            client,
            {
                "preferences": {
                    "discover_enabled": False,
                    "sidebar_transparency": "60",
                    "lightbox_zoom_level": 2,
                }
            },
        )
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True

        prefs = _get_prefs(client)
        assert prefs["discover_enabled"] is False
        assert prefs["sidebar_transparency"] == "60"
        assert prefs["lightbox_zoom_level"] == 2
        # 未保存的键回退默认值
        assert prefs["image_quality"] == "high"

    def test_bare_dict_form_saved_and_read_back(self, client, app, prefs_file):
        """裸字典形态（向后兼容）：保存后读回同样生效"""
        _login(client, app)
        resp = _post_prefs(client, {"discover_format": "three"})
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True

        prefs = _get_prefs(client)
        assert prefs["discover_format"] == "three"

    def test_second_save_overwrites(self, client, app, prefs_file):
        """再次保存覆盖旧值，且包裹形态与裸字典可混用"""
        _login(client, app)
        _post_prefs(client, {"preferences": {"discover_enabled": False}})
        _post_prefs(client, {"discover_enabled": True})
        prefs = _get_prefs(client)
        assert prefs["discover_enabled"] is True

    def test_saved_keys_merge_with_defaults(self, client, app, prefs_file):
        """保存键与默认键在读回时合并，所有默认键仍然存在"""
        _login(client, app)
        _post_prefs(client, {"preferences": {"sidebar_transparency": "40"}})
        prefs = _get_prefs(client)
        for key in (
            "discover_enabled",
            "discover_format",
            "discover_rounded",
            "discover_shape",
            "discover_size",
            "sidebar_transparency",
            "lightbox_zoom_level",
            "image_quality",
            "autoplay_lightbox",
        ):
            assert key in prefs


class TestPageRendersSavedPreferences:
    """页面路由渲染时注入已保存偏好（bug #7）"""

    def _extract_server_prefs(self, html):
        match = re.search(r"const serverPreferences = (\{.*?\});", html)
        assert match, "模板未渲染 serverPreferences"
        return json.loads(match.group(1))

    def test_index_injects_saved_preferences(self, client, app, prefs_file):
        """/gallery/ 首页渲染注入的 user_preferences 与已存偏好一致"""
        _login(client, app)
        _post_prefs(
            client,
            {
                "preferences": {
                    "discover_enabled": False,
                    "sidebar_transparency": "60",
                }
            },
        )
        resp = client.get("/gallery/")
        assert resp.status_code == 200
        server_prefs = self._extract_server_prefs(resp.get_data(as_text=True))
        assert server_prefs["discover_enabled"] is False
        assert server_prefs["sidebar_transparency"] == "60"

    def test_browse_injects_saved_preferences(self, client, app, prefs_file, tmp_path, monkeypatch):
        """/gallery/<path> 渲染同样注入已存偏好"""
        # 构造临时画廊根目录与子目录（含一张图片）
        gallery_root = tmp_path / "gallery_root"
        sub = gallery_root / "sub"
        sub.mkdir(parents=True)
        (sub / "pic.jpg").write_bytes(b"fake")
        config_file = tmp_path / "config.json"
        config_file.write_text(
            json.dumps({"paths": {"gallery_root_path": str(gallery_root)}}),
            encoding="utf-8",
        )
        monkeypatch.setattr("Module.common.config_utils.CONFIG_FILE", config_file)

        _login(client, app)
        _post_prefs(
            client,
            {"preferences": {"lightbox_zoom_level": 2}},
        )
        resp = client.get("/gallery/sub")
        assert resp.status_code == 200
        server_prefs = self._extract_server_prefs(resp.get_data(as_text=True))
        assert server_prefs["lightbox_zoom_level"] == 2


class TestUnauthenticatedBehavior:
    """未登录行为不回归（全局认证中间件先重定向到登录页）"""

    def test_get_preferences_unauthenticated_redirects(self, client, app, prefs_file):
        """未登录 GET 被认证中间件重定向到登录页（既有行为）"""
        resp = client.get("/gallery/api/preferences")
        assert resp.status_code == 302
        assert resp.location.endswith("/login")

    def test_post_preferences_unauthenticated_redirects(self, client, app, prefs_file):
        """未登录 POST 被认证中间件重定向到登录页（既有行为）"""
        resp = client.post(
            "/gallery/api/preferences",
            json={"preferences": {"discover_enabled": False}},
            headers={"X-CSRF-Token": CSRF_TOKEN},
        )
        assert resp.status_code == 302
        assert resp.location.endswith("/login")

    def test_get_default_preferences_unauthenticated_redirects(self, client, app, prefs_file):
        """未登录默认偏好端点同样被重定向（既有行为）"""
        resp = client.get("/gallery/api/preferences/default")
        assert resp.status_code == 302
        assert resp.location.endswith("/login")

    def test_preferences_file_written_to_tmp(self, client, app, prefs_file):
        """保存写入的是重定向后的临时文件，不触碰生产文件"""
        _login(client, app)
        _post_prefs(client, {"preferences": {"discover_enabled": False}})
        assert prefs_file.exists()
        on_disk = json.loads(prefs_file.read_text(encoding="utf-8"))
        assert on_disk["users"]["alice"]["discover_enabled"] is False
