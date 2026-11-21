"""
首页服务端渲染与发现区限量缓存测试（ADR-0012）

- 首页挂载入口由服务端渲染（HTML 直接包含链接，不依赖前端 fetch）
- 首页壁纸 URL 服务端渲染（preload + 内联背景），按文件名寻址
- /static/wallpaper?img=<文件名> 直接服务指定壁纸；非法名 404
- /gallery/api/random-images：≤36 张、结果缓存（二次调用不重新扫描）
"""

import pytest

from Module.common import user_utils

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


def _login(client):
    user_utils.save_users({"bob": {"id": 1001, "username": "bob", "password": "p",
                                   "role": "user", "enabled": True}})
    with client.session_transaction() as sess:
        sess["user_id"] = 1001
        sess["username"] = "bob"
        sess["role"] = "user"
        sess["verified"] = True


def _config(wallpaper_path=None):
    cfg = {
        "settings": {"wallpaper_enabled": True, "mounted_pages_enabled": True},
        "wallpaper": {"enabled": bool(wallpaper_path), "path": wallpaper_path or ""},
        "mounted_pages": [{"name": "demo-page", "path": "x", "is_file": False}],
    }
    return cfg


class TestHomeServerRendered:
    def test_mounted_pages_server_rendered(self, client, app, tmp_path, monkeypatch):
        cfg = _config()
        monkeypatch.setattr("Module.index.index.load_config", lambda: cfg)
        _login(client)

        body = client.get("/", headers={"User-Agent": BROWSER_UA}).get_data(as_text=True)

        assert 'href="/demo-page"' in body
        # 不再依赖前端 fetch 渲染入口
        assert "/api/mounted-pages" not in body

    def test_wallpaper_url_server_rendered(self, client, app, tmp_path, monkeypatch):
        cfg = _config("Module/static/wallpaper")
        monkeypatch.setattr("Module.index.index.load_config", lambda: cfg)
        _login(client)

        body = client.get("/", headers={"User-Agent": BROWSER_UA}).get_data(as_text=True)

        assert "/static/wallpaper?img=" in body
        assert 'rel="preload" as="image"' in body


class TestWallpaperByName:
    def test_serve_named_wallpaper(self, client, app, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "Module.index.index.load_config", lambda: _config("Module/static/wallpaper")
        )
        _login(client)

        resp = client.get(
            "/static/wallpaper?img=1.jpg", headers={"User-Agent": BROWSER_UA}
        )
        assert resp.status_code == 200
        assert resp.mimetype == "image/jpeg"

    def test_reject_bad_wallpaper_name(self, client, app, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "Module.index.index.load_config", lambda: _config("Module/static/wallpaper")
        )
        _login(client)

        resp = client.get(
            "/static/wallpaper?img=..%2Fsecret.jpg", headers={"User-Agent": BROWSER_UA}
        )
        assert resp.status_code == 404


class TestDiscoverLayoutStability:
    """发现区加载前后布局稳定（渲染完成才显示 + 先应用布局参数）"""

    JS = "Module/static/gallery/js/gallery-page.js"

    def _load_random_images_body(self):
        from pathlib import Path

        src = Path(self.JS).read_text(encoding="utf-8")
        start = src.index("function loadRandomImages")
        rest = src[start + 1 :]
        end = rest.index("\n        function ")
        return src[start : start + 1 + end]

    def test_section_shown_only_after_render(self):
        body = self._load_random_images_body()
        assert "discoverSection.classList.add('visible')" in body

    def test_layout_applied_before_items_inserted(self):
        body = self._load_random_images_body()
        # 插入前先派发一次布局应用事件（空网格上设定最终列数/尺寸）
        first_dispatch = body.index("discover:images-rendered")
        insert_pos = body.index("replaceChildren(")
        assert first_dispatch < insert_pos

    def test_no_immediate_visible_in_apply_user_preferences(self):
        from pathlib import Path

        src = Path(self.JS).read_text(encoding="utf-8")
        start = src.index("function applyUserPreferences")
        body = src[start : src.index("function ", start + 1)]
        assert "classList.add('visible')" not in body

class TestRandomImagesLimitedCached:
    def _make_root(self, tmp_path, folders=10, per_folder=5):
        root = tmp_path / "gallery"
        root.mkdir()
        for i in range(folders):
            d = root / f"f{i}"
            d.mkdir()
            for j in range(per_folder):
                (d / f"img{j}.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)
        return root

    def test_limited_count_and_cached(self, client, app, tmp_path, monkeypatch):
        from Module.core.gallery_service import GalleryService

        root = self._make_root(tmp_path)
        monkeypatch.setattr(GalleryService, "get_gallery_root", lambda self: root)
        calls = {"n": 0}
        original = GalleryService.get_all_subfolders_recursive

        def counting(self, folder_path):
            # 只统计根目录的递归入口（内部递归不计数）
            if str(folder_path) == str(root):
                calls["n"] += 1
            return original(self, folder_path)

        monkeypatch.setattr(GalleryService, "get_all_subfolders_recursive", counting)
        _login(client)

        r1 = client.get("/gallery/api/random-images", headers={"User-Agent": BROWSER_UA})
        data1 = r1.get_json()
        assert data1["success"] is True
        assert 0 < len(data1["images"]) <= 36

        r2 = client.get("/gallery/api/random-images", headers={"User-Agent": BROWSER_UA})
        data2 = r2.get_json()
        assert data2["images"] == data1["images"]  # 命中缓存
        assert calls["n"] == 1  # 第二次没有重新扫描
