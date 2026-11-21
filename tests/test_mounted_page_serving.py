"""
挂载服务行为锚定测试 + 子目录尾斜杠重定向（挂载纯前端站优化·任务 2）

锚定 serve_mounted_page 的既有行为：
- 目录根无尾斜杠 → 302 到 /<name>/（既有）
- 目录根带尾斜杠 → 200 返回 index.html（既有）
- 子路径文件按 MIME 200 返回（既有）
- 子路径 .. 穿越 → 403（既有安全校验，不得削弱）
- 未知挂载页 → 404（既有）
- 匿名访问 → 302 重定向登录页（既有，挂载页不在认证白名单）
并驱动行为变更（ADR-0002）：
- 子目录含 index.html 时无尾斜杠 → 302 到 /<name>/<sub>/（原实现直接 200，
  子目录内相对资源解析错位——本测试先 FAIL 后实现补齐）

fixture 设计要点：挂载路径校验是 resolved_path.relative_to(app_root)（app_root
= 项目根），故临时挂载目录必须建在项目根内且不在 SENSITIVE_DIRS
（.git / Module/data / Module/json）——选 Module/static/ 下临时目录，
teardown 时 rmtree 清理；挂载记录 path 用绝对路径，绕开 app_root 相对拼接歧义。
"""

import json
import shutil
from pathlib import Path

import pytest

from Module.common import user_utils

PROJECT_ROOT = Path(__file__).resolve().parents[1]
# 项目根内且不在 SENSITIVE_DIRS（.git / Module/data / Module/json）
MOUNT_BASE = PROJECT_ROOT / "Module" / "static"


def _rmtree_retry(path, attempts=4):
    """带重试的目录删除（Windows 下 send_file 句柄可能延迟释放导致部分删除失败）"""
    import time

    for i in range(attempts):
        shutil.rmtree(path, ignore_errors=True)
        if not path.exists():
            return
        time.sleep(0.2 * (i + 1))


@pytest.fixture
def mount_root():
    """
    项目根内的临时挂载目录（唯一名防同 session 内相互覆盖），测试后清理。

    建目录前清扫历史 mount_test_* 残留（上一轮清理因文件锁部分失败时的兜底）。
    """
    import uuid

    MOUNT_BASE.mkdir(parents=True, exist_ok=True)
    for stale in MOUNT_BASE.glob("mount_test_*"):
        _rmtree_retry(stale)
    base = MOUNT_BASE / f"mount_test_{uuid.uuid4().hex[:8]}"
    base.mkdir()
    yield base
    _rmtree_retry(base)


@pytest.fixture
def config_file(tmp_path, monkeypatch):
    """
    将配置文件重定向到临时文件（模式照抄 test_admin_mounted_pages.py 并扩展）：

    index.py 自带模块级 CONFIG_FILE（挂载页列表读取），
    功能开关（mounted_pages_enabled）走 config_utils.CONFIG_FILE——两处都要重定向。
    """
    target = tmp_path / "config.json"
    monkeypatch.setattr("Module.common.config_utils.CONFIG_FILE", target)
    monkeypatch.setattr("Module.common.config_utils.CONFIG_FILE", target)
    return target


@pytest.fixture
def mounted_site(mount_root, config_file):
    """
    标准目录挂载结构并写入挂载记录：

    site/
    ├── index.html          # 根 index
    ├── pages/index.html    # 子目录 index（驱动 302 重定向）
    └── static/app.js       # 子路径静态资源
    """
    site = mount_root / "site"
    (site / "static").mkdir(parents=True)
    (site / "pages").mkdir()
    (site / "index.html").write_text(
        "<html><body>docsx root index</body></html>", encoding="utf-8"
    )
    (site / "pages" / "index.html").write_text(
        "<html><body>pages index</body></html>", encoding="utf-8"
    )
    (site / "static" / "app.js").write_text(
        "console.log('app');", encoding="utf-8"
    )
    config_file.write_text(
        json.dumps(
            {
                "mounted_pages": [
                    {"name": "docsx", "path": str(site), "type": "directory"}
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return site


def _login(client):
    """注入登录态（挂载页不在认证白名单，匿名会被重定向登录页）"""
    user_utils.save_users(
        {
            "admin": {
                "id": 0,
                "username": "admin",
                "password": "p",
                "role": "admin",
                "enabled": True,
            }
        }
    )
    with client.session_transaction() as sess:
        sess["user_id"] = 0
        sess["username"] = "admin"
        sess["role"] = "admin"
        sess["verified"] = True


@pytest.fixture
def logged_client(client, app, mounted_site):
    """带登录态与标准挂载结构的测试客户端"""
    _login(client)
    return client


class TestMountedPageServing:
    def test_dir_mount_redirects_to_trailing_slash(self, logged_client):
        """GET /docsx → 302，Location == /docsx/（既有行为锚定）"""
        resp = logged_client.get("/docsx")

        assert resp.status_code == 302
        assert resp.headers["Location"] == "/docsx/"

    def test_dir_mount_serves_index_with_trailing_slash(self, logged_client):
        """GET /docsx/ → 200，返回根 index.html 内容（既有行为锚定）"""
        resp = logged_client.get("/docsx/")

        assert resp.status_code == 200
        assert "<html" in resp.data.decode()
        assert "docsx root index" in resp.data.decode()

    def test_subpath_asset_served(self, logged_client):
        """GET /docsx/static/app.js → 200，返回文件内容（既有行为锚定）"""
        resp = logged_client.get("/docsx/static/app.js")

        assert resp.status_code == 200
        assert "console.log('app');" in resp.data.decode()

    def test_subpath_traversal_rejected(self, logged_client):
        """GET /docsx/..%2fx → 403（既有防穿越安全校验锚定）"""
        resp = logged_client.get("/docsx/..%2fx")

        assert resp.status_code == 403

    def test_subdir_index_redirects_to_trailing_slash(self, logged_client):
        """GET /docsx/pages（子目录含 index.html，无尾斜杠）→ 302 到 /docsx/pages/

        当前实现直接 200 返回 index.html（L365-368 无重定向），子目录内相对
        资源会解析错位——本测试先 FAIL，补齐重定向后通过（ADR-0002）。
        """
        resp = logged_client.get("/docsx/pages")

        assert resp.status_code == 302
        assert resp.headers["Location"] == "/docsx/pages/"

    def test_unknown_page_404(self, logged_client):
        """GET 未挂载的页面名 → 404（既有行为锚定）"""
        resp = logged_client.get("/no-such-mounted-page-xyz")

        assert resp.status_code == 404

    def test_anonymous_redirects_to_login(self, client, app, mounted_site):
        """匿名 GET /docsx → 302 重定向登录页（挂载页不在认证白名单）"""
        resp = client.get("/docsx")

        assert resp.status_code == 302
        assert "/user/login" in resp.headers["Location"]


@pytest.fixture
def spa_client(client, app, spa_site):
    """带登录态与绝对引用形态挂载站的测试客户端"""
    _login(client)
    return client


@pytest.fixture
def spa_site(mount_root, config_file):
    """
    绝对引用形态站（复刻 it-tools：Vite base:'/'，站根绝对引用）并写入挂载记录：

    spa/
    ├── index.html                      # src|href="/..." 站根绝对引用 + 保守例外
    └── assets/
        ├── index-61effc08.js
        └── index-5da4700d.css
    """
    site = mount_root / "spa"
    (site / "assets").mkdir(parents=True)
    (site / "index.html").write_text(
        "<!doctype html><html><head>\n"
        '<script type="module" src="/assets/index-61effc08.js"></script>\n'
        '<link rel="stylesheet" href="/assets/index-5da4700d.css">\n'
        '<link rel="manifest" href="/manifest.webmanifest">\n'
        '<script src="static/rel.js"></script>\n'
        "</head><body>\n"
        '<a href="/">home</a><a href="//cdn/x">proto</a>\n'
        '<a href="https://ext.example/a.js">ext</a><a href="#top">anchor</a>\n'
        "</body></html>",
        encoding="utf-8",
    )
    (site / "assets" / "index-61effc08.js").write_text(
        "console.log(1);", encoding="utf-8"
    )
    (site / "assets" / "index-5da4700d.css").write_text("body{}", encoding="utf-8")
    config_file.write_text(
        json.dumps(
            {"mounted_pages": [{"name": "spa", "path": str(site), "type": "directory"}]},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return site


class TestMountedHtmlAbsoluteRefRewrite:
    """挂载 HTML 站根绝对引用重写（任务 4，ADR-0002）

    it-tools 型（Vite base:'/'）构建产物在挂载子路径下，站根绝对引用
    /assets/* 必 404——服务挂载 HTML 时把 src|href="/..." 重写为 /<name>/...；
    保守规则：裸 "/"、// 协议相对、外链、data:、锚点、相对路径全部不动。
    """

    def test_absolute_refs_rewritten(self, spa_client):
        """GET /spa/ → 200；绝对引用被重写为挂载前缀，原始 /assets/ 引用不再出现"""
        resp = spa_client.get("/spa/")

        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert 'src="/spa/assets/index-61effc08.js"' in body
        assert 'href="/spa/manifest.webmanifest"' in body
        # 反向断言：站根绝对引用形态不得残留在响应中
        assert 'src="/assets/' not in body
        assert 'href="/assets/' not in body

    def test_absolute_ref_target_served(self, spa_client):
        """重写后的资源 URL 可达：GET /spa/assets/index-61effc08.js → 200 text/javascript"""
        resp = spa_client.get("/spa/assets/index-61effc08.js")

        assert resp.status_code == 200
        assert _content_type(resp) == "text/javascript"
        assert "console.log(1);" in resp.get_data(as_text=True)

    def test_rewrite_conservative_cases(self, spa_client):
        """保守例外原样保留：裸 "/"、协议相对、外链、锚点、相对路径不被重写"""
        resp = spa_client.get("/spa/")

        body = resp.get_data(as_text=True)
        assert 'href="/"' in body
        assert 'href="//cdn/x"' in body
        assert 'href="https://ext.example/a.js"' in body
        assert 'href="#top"' in body
        assert 'src="static/rel.js"' in body


def _write_asset(site, filename, content="x"):
    """在挂载站 static/ 下写一个测试资源文件"""
    path = site / "static" / filename
    path.write_text(content, encoding="utf-8")
    return path


def _content_type(resp):
    """响应媒体类型（Werkzeug 为 text/* 自动附加 "; charset=utf-8"，比较时剥离参数）"""
    return resp.headers["Content-Type"].split(";")[0].strip()


class TestMountedMimeTable:
    """挂载静态文件显式 MIME 表（任务 3，ADR-0002）

    显式表优先于 mimetypes 猜测：<script type="module">、ESM、wasm 等对
    Content-Type 有严格校验，猜测失败（None）会落 octet-stream 被浏览器拒绝。
    """

    def test_explicit_mime_beats_guess(self, logged_client, mounted_site, monkeypatch):
        """猜测返回 None 时表项仍生效：.js → text/javascript（而非 octet-stream）"""
        monkeypatch.setattr(
            "Module.core.index_service.mimetypes.guess_type", lambda p: (None, None)
        )

        resp = logged_client.get("/docsx/static/app.js")

        assert resp.status_code == 200
        assert _content_type(resp) == "text/javascript"

    @pytest.mark.parametrize(
        "filename,expected",
        [
            ("app.mjs", "text/javascript"),
            ("style.css", "text/css"),
            ("icon.svg", "image/svg+xml"),
            ("core.wasm", "application/wasm"),
            ("f.woff2", "font/woff2"),
            ("manifest.webmanifest", "application/manifest+json"),
        ],
    )
    def test_mime_table_values(self, logged_client, mounted_site, filename, expected):
        """表内后缀的文件按显式表返回 Content-Type（GET /docsx/static/<filename>）"""
        _write_asset(mounted_site, filename)

        resp = logged_client.get(f"/docsx/static/{filename}")

        assert resp.status_code == 200
        assert _content_type(resp) == expected
