"""
画廊重写行为锚定（ADR-0009）：三蓝图守卫统一 + 静态资产可达
"""

import pytest

from Module.common import user_utils


def _set_gallery_disabled(monkeypatch, enabled):
    """直接打桩 common.settings_utils.is_feature_enabled，避免写生产 config"""
    def fake(feature_key):
        if feature_key == "gallery_enabled":
            return enabled
        return True

    monkeypatch.setattr(
        "Module.common.settings_utils.is_feature_enabled",
        fake,
    )


def _login(client):
    user_utils.save_users({"bob": {"id": 1001, "username": "bob", "password": "p",
                                   "role": "user", "enabled": True}})
    with client.session_transaction() as s:
        s["user_id"] = 1001
        s["username"] = "bob"
        s["role"] = "user"
        s["verified"] = True


class TestGalleryEnabledGuard:
    """三蓝图 gallery_enabled 关闭时均重定向首页（去重后行为不变）"""

    @pytest.mark.parametrize("path", [
        "/gallery",
        "/gallery/api/favorites",
        "/gallery/api/preferences",
        "/gallery/api/random-images",
    ])
    def test_disabled_redirects_home(self, client, app, monkeypatch, path):
        # 必须先登录：全局认证中间件先于蓝图 guard 执行，
        # 未登录会被拦去 /user/login 而非观测到 guard 的重定向
        _login(client)
        _set_gallery_disabled(monkeypatch, False)
        resp = client.get(path)
        assert resp.status_code == 302
        assert resp.location.endswith("/")

    @pytest.mark.parametrize("path", [
        "/gallery/api/favorites",
        "/gallery/api/preferences",
    ])
    def test_enabled_passes_guard(self, client, app, monkeypatch, path):
        _set_gallery_disabled(monkeypatch, True)
        _login(client)
        resp = client.get(path)
        assert resp.status_code == 200


class TestGalleryStaticAssets:
    """静态资产经全局 /static/ 可达（ADR-0009：ipguard 白名单内）"""

    def test_css_asset_reachable(self, client, app, monkeypatch):
        from pathlib import Path

        asset = Path("Module/static/gallery/css/gallery.css")
        assert asset.is_file()
        resp = client.get("/static/gallery/css/gallery.css")
        assert resp.status_code == 200
        assert resp.mimetype == "text/css"


class TestGalleryJsExtraction:
    """模板源码结构锚定：注入三行在外部脚本之前 + 整块脚本已外置"""

    TEMPLATE = "Module/gallery/templates/gallery/index.html"
    JS_ASSET = "Module/static/gallery/js/gallery-page.js"

    def test_injection_lines_before_external_scripts(self):
        from pathlib import Path

        src = Path(self.TEMPLATE).read_text(encoding="utf-8")
        i_prefs = src.index("const serverPreferences = ")
        i_csrf = src.index("window.csrfToken = ")
        i_ext = src.index("gallery/js/gallery-page.js")
        assert i_prefs < i_ext and i_csrf < i_ext

    def test_expected_js_assets_exist(self):
        from pathlib import Path

        assert Path(self.JS_ASSET).is_file()

    def test_js_asset_reachable(self, client, app):
        resp = client.get("/static/gallery/js/gallery-page.js")
        assert resp.status_code == 200
        assert "javascript" in resp.mimetype

    def test_swipe_inplace_semantics_preserved(self):
        """滑动原地换图 6 点语义保留（ADR-0009 承诺）"""
        from pathlib import Path

        src = Path(self.JS_ASSET).read_text(encoding="utf-8")
        swipe = src[src.index("function setupSwipeNavigation"):]
        assert "window.innerWidth" in swipe
        assert "lightboxImage.src = nextUrl" in swipe
        assert "openLightbox(nextUrl)" not in swipe
        assert "_discoverCurrentIndex + dir + list.length" in swipe
        assert "checkFavoriteStatus(nextUrl)" in swipe


class TestFavoritesSharedBlocks:
    """收藏页：CSS 外置 + 灯箱 markup 走公共 include（ADR-0009 G5）"""

    FAV = "Module/gallery/templates/gallery/favorites.html"

    def test_favorites_css_externalized(self):
        from pathlib import Path

        assert Path("Module/static/gallery/css/favorites.css").is_file()
        src = Path(self.FAV).read_text(encoding="utf-8")
        assert "static_url('gallery/css/favorites.css')" in src
        assert "<style>" not in src

    def test_favorites_lightbox_via_include(self):
        from pathlib import Path

        src = Path(self.FAV).read_text(encoding="utf-8")
        assert "{% include 'gallery/_lightbox.html' %}" in src
        frag = Path("Module/gallery/templates/gallery/_lightbox.html").read_text(encoding="utf-8")
        assert 'id="lightboxImage"' in frag and "lightbox-favorite" in frag

    def test_index_lightbox_via_include(self):
        from pathlib import Path

        src = Path("Module/gallery/templates/gallery/index.html").read_text(encoding="utf-8")
        assert "{% include 'gallery/_lightbox.html' %}" in src
