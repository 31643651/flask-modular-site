"""
index.html 壁纸配置保存 CSRF 头回归测试

背景：saveWallpaperConfig 对 /api/wallpaper/config 发起 POST 时
未携带 X-CSRF-Token 头，被全局 CSRF 中间件（security.py 的
init_csrf_middleware，豁免仅 /user/login、/user/verify、/setup）
拦截返回 403，首页壁纸开关功能完全不可用（bug #1，高危）。
本测试防止回归。
"""

import re
from pathlib import Path

import pytest
from jinja2 import Environment

TEMPLATE_PATH = (
    Path(__file__).resolve().parent.parent
    / "Module" / "index" / "templates" / "index" / "index.html"
)
UI_JS_PATH = (
    Path(__file__).resolve().parent.parent
    / "Module" / "static" / "common" / "ui.js"
)

_SCRIPT_BLOCK_RE = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", re.DOTALL)
# 抓取 method 为 POST/PUT/DELETE/PATCH 的 fetch 调用（保守匹配至调用起始括号后）
_MUTATING_FETCH_RE = re.compile(
    r"fetch\((?P<call>[^;]*?method\s*:\s*['\"](?:POST|PUT|DELETE|PATCH)['\"][^;]*?)\}\)",
    re.DOTALL,
)


@pytest.fixture(scope="module")
def template_source() -> str:
    return TEMPLATE_PATH.read_text(encoding="utf-8")


def test_template_exists():
    assert TEMPLATE_PATH.is_file(), f"模板文件不存在: {TEMPLATE_PATH}"


def test_jinja_parse(template_source):
    """模板必须可通过 Jinja 语法解析。"""
    Environment().parse(template_source)


def _mutating_fetches(template_source):
    """提取所有 POST/PUT/DELETE/PATCH 的 fetch 调用文本。"""
    # 只分析内联 script 块，避免误匹配外链脚本标签内容
    blocks = "".join(m.group(1) for m in _SCRIPT_BLOCK_RE.finditer(template_source))
    return list(_MUTATING_FETCH_RE.finditer(blocks))


def test_every_mutating_fetch_has_csrf_header(template_source):
    """所有 POST/PUT/DELETE fetch 必须携带 X-CSRF-Token 头。"""
    calls = _mutating_fetches(template_source)
    assert calls, "未检测到任何 mutating fetch（测试失效，需更新正则）"
    for m in calls:
        call = m.group("call")
        assert "X-CSRF-Token" in call, (
            "发现缺少 X-CSRF-Token 头的 POST/PUT/DELETE fetch：\n" + call
        )


def test_save_wallpaper_config_uses_getcsrf_token(template_source):
    """saveWallpaperConfig 必须通过 getCsrfToken() 取 token。

    getCsrfToken 已收敛到公共 ui.js（优先 window.csrfToken，回退 cookie），
    模板通过外链脚本获得该函数。
    """
    blocks = "".join(m.group(1) for m in _SCRIPT_BLOCK_RE.finditer(template_source))
    assert "function saveWallpaperConfig(" in blocks
    m = re.search(
        r"function saveWallpaperConfig\(.*?\n        \}", blocks, re.DOTALL
    )
    assert m, "无法定位 saveWallpaperConfig 函数体"
    assert "getCsrfToken()" in m.group(0)
    assert '<script src="/static/common/ui.js"></script>' in template_source
    ui_source = UI_JS_PATH.read_text(encoding="utf-8")
    assert re.search(r"function\s+getCsrfToken\s*\(", ui_source)


def test_getcsrf_token_helper_available_to_inline_script(template_source):
    """内联脚本使用的 getCsrfToken 必须由公共 ui.js 提前提供。"""
    assert '<script src="/static/common/ui.js"></script>' in template_source
    ui_source = UI_JS_PATH.read_text(encoding="utf-8")
    assert re.search(r"function\s+getCsrfToken\s*\(", ui_source)
    assert re.search(r"function\s+getCookie\s*\(", ui_source)
    assert "window.csrfToken" in ui_source
