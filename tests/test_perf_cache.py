"""
HTTP 缓存策略测试（ADR-0011）

- HTML 页面：no-store（动态页面不缓存）
- /static/ 带版本号（?v=）：immutable 一年
- /static/ 无版本号：1 小时
- 图片（image/*）：1 天
- JSON API：不设 max-age（不被缓存）
- 画廊页面静态引用带版本号（static_url）
"""

import pytest

from Module.common import user_utils

CSRF_TOKEN = "test-csrf-token"
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
        sess["csrf_token"] = CSRF_TOKEN


class TestHtmlNoStore:
    def test_home_html_no_store(self, client, app):
        _login(client)
        resp = client.get("/", headers={"User-Agent": BROWSER_UA})
        assert resp.mimetype == "text/html"
        assert resp.headers.get("Cache-Control") == "no-store"

    def test_gallery_html_no_store(self, client, app):
        _login(client)
        resp = client.get("/gallery", headers={"User-Agent": BROWSER_UA})
        assert resp.headers.get("Cache-Control") == "no-store"


class TestStaticCache:
    def test_versioned_gallery_static_immutable(self, client, app):
        resp = client.get("/static/gallery/css/gallery.css?v=123")
        assert resp.status_code == 200
        assert "max-age=31536000" in resp.headers.get("Cache-Control", "")
        assert "immutable" in resp.headers.get("Cache-Control", "")

    def test_unversioned_static_one_hour(self, client, app):
        resp = client.get("/static/favicon.ico")
        assert resp.status_code == 200
        assert "max-age=3600" in resp.headers.get("Cache-Control", "")


class TestImageCache:
    def test_gallery_image_one_day(self, client, app, tmp_path, monkeypatch):
        from Module.core.gallery_service import GalleryService

        root = tmp_path / "gallery_root"
        root.mkdir()
        (root / "a.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)
        monkeypatch.setattr(GalleryService, "get_gallery_root", lambda self: root)
        _login(client)

        resp = client.get("/gallery/image/a.png", headers={"User-Agent": BROWSER_UA})
        assert resp.status_code == 200
        assert resp.mimetype == "image/png"
        assert "max-age=86400" in resp.headers.get("Cache-Control", "")


class TestApiNotCached:
    def test_json_api_has_no_max_age(self, client, app):
        _login(client)
        resp = client.get("/gallery/api/random-images", headers={"User-Agent": BROWSER_UA})
        assert resp.status_code == 200
        cache = resp.headers.get("Cache-Control", "")
        assert "max-age" not in cache


class TestStaticUrlVersioning:
    def test_gallery_page_uses_versioned_static(self, client, app):
        _login(client)
        body = client.get("/gallery", headers={"User-Agent": BROWSER_UA}).get_data(as_text=True)
        assert "/static/gallery/css/gallery.css?v=" in body
        assert "/static/gallery/js/gallery-page.js?v=" in body

    def test_favorites_page_uses_versioned_static(self, client, app):
        _login(client)
        body = client.get(
            "/gallery/favorites", headers={"User-Agent": BROWSER_UA}
        ).get_data(as_text=True)
        assert "/static/gallery/css/favorites.css?v=" in body
