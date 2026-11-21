"""
画廊搜索 API 测试：结果文件夹补齐 cover/count 字段（bug #8）

对照 browse 接口（_build_gallery_data）的文件夹结构：
{path, name, count, cover}
"""

import json
from pathlib import Path

import pytest

from Module.common import user_utils


def _rel(*parts):
    """与后端 get_relative_path 一致：Path 的 str 形式（Windows 下为反斜杠）"""
    return str(Path(*parts))


@pytest.fixture
def gallery_root(tmp_path, monkeypatch):
    """构造临时画廊根目录，并把 config.json 重定向到临时文件"""
    root = tmp_path / "gallery_root"
    root.mkdir()
    config_file = tmp_path / "config.json"
    config_file.write_text(
        json.dumps({"paths": {"gallery_root_path": str(root)}}),
        encoding="utf-8",
    )
    monkeypatch.setattr("Module.common.config_utils.CONFIG_FILE", config_file)
    return root


@pytest.fixture
def logged_in(client, app):
    """创建用户并注入登录态"""
    user_utils.save_users(
        {
            "alice": {
                "id": 1,
                "username": "alice",
                "password": "pass123",
                "role": "user",
                "enabled": True,
            },
        }
    )
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["username"] = "alice"
        sess["role"] = "user"
        sess["verified"] = True


def _search(client, query):
    return client.get("/gallery/api/search", query_string={"q": query})


class TestSearchFoldersHaveCoverAndCount:
    """搜索结果文件夹必须带 cover/count 且与 browse 口径一致（bug #8 主修复）"""

    def test_folder_with_images(self, client, app, gallery_root, logged_in):
        """含图片的文件夹：cover 为首图 URL，count 为图片总数"""
        sub = gallery_root / "vacation"
        sub.mkdir()
        (sub / "b.jpg").write_bytes(b"fake")
        (sub / "a.jpg").write_bytes(b"fake")

        resp = _search(client, "vacation")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True

        folders = data["results"]["folders"]
        assert len(folders) == 1
        folder = folders[0]
        assert folder["path"] == "vacation"
        assert folder["name"] == "vacation"
        assert folder["count"] == 2
        # 首图按名称排序取第一个（与 browse 的 get_first_image 口径一致）
        assert folder["cover"] == "/gallery/image/" + _rel("vacation", "a.jpg")

    def test_empty_folder(self, client, app, gallery_root, logged_in):
        """空文件夹：count 为 0，cover 为 None（前端走占位图标分支）"""
        (gallery_root / "empty").mkdir()

        resp = _search(client, "empty")
        assert resp.status_code == 200
        folders = resp.get_json()["results"]["folders"]
        assert len(folders) == 1
        folder = folders[0]
        assert folder["count"] == 0
        assert folder["cover"] is None

    def test_count_includes_nested_subfolder_images(
        self, client, app, gallery_root, logged_in
    ):
        """count 口径为递归计数（与 browse 的 count_images_in_folder 一致）"""
        sub = gallery_root / "trip"
        nested = sub / "day1"
        nested.mkdir(parents=True)
        (sub / "root.jpg").write_bytes(b"fake")
        (nested / "nested.jpg").write_bytes(b"fake")

        resp = _search(client, "trip")
        folders = resp.get_json()["results"]["folders"]
        assert len(folders) == 1
        folder = folders[0]
        assert folder["count"] == 2
        # cover 深度优先取子文件夹首图（与 browse 的 get_first_image 口径一致）
        assert folder["cover"] == "/gallery/image/" + _rel("trip", "day1", "nested.jpg")

    def test_nested_folder_matched_by_name(self, client, app, gallery_root, logged_in):
        """深层子文件夹命中搜索时同样携带字段，path 为相对路径"""
        parent = gallery_root / "album"
        child = parent / "beach"
        child.mkdir(parents=True)
        (child / "sunset.jpg").write_bytes(b"fake")

        resp = _search(client, "beach")
        folders = resp.get_json()["results"]["folders"]
        assert len(folders) == 1
        folder = folders[0]
        assert folder["path"] == _rel("album", "beach")
        assert folder["name"] == "beach"
        assert folder["count"] == 1
        assert folder["cover"] == "/gallery/image/" + _rel("album", "beach", "sunset.jpg")


class TestSearchResponseStructureNotRegressed:
    """搜索响应其余结构不回归"""

    def test_empty_query_returns_empty_results(self, client, app, gallery_root, logged_in):
        resp = _search(client, "   ")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["results"] == {"folders": [], "images": []}

    def test_image_results_shape_unchanged(self, client, app, gallery_root, logged_in):
        """图片命中的 url/name 结构保持原样"""
        (gallery_root / "sunset_photo.jpg").write_bytes(b"fake")

        resp = _search(client, "sunset")
        assert resp.status_code == 200
        images = resp.get_json()["results"]["images"]
        assert len(images) == 1
        assert images[0] == {
            "url": "/gallery/image/sunset_photo.jpg",
            "name": "sunset_photo.jpg",
        }

    def test_folder_keys_still_include_path_and_name(
        self, client, app, gallery_root, logged_in
    ):
        """文件夹字段在补齐后仍保留原有 path/name（向后兼容）"""
        (gallery_root / "misc").mkdir()
        resp = _search(client, "misc")
        folder = resp.get_json()["results"]["folders"][0]
        assert set(folder.keys()) == {"path", "name", "count", "cover"}

    def test_no_match_returns_empty(self, client, app, gallery_root, logged_in):
        (gallery_root / "something").mkdir()
        resp = _search(client, "不存在的关键词xyz")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["results"]["folders"] == []
        assert data["results"]["images"] == []
