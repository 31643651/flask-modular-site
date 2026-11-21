"""
壁纸接口权限与 HTTPException 透传测试（bug #20 + #21）

- #20：POST /api/wallpaper/config 仅超级管理员可改
  （未登录 401 JSON、普通用户 403 JSON 对齐 response.py 统一格式、
  超管未过二次验证 302 跳验证页、超管 200 且配置生效）
- #20：enabled 强转——布尔直通、字符串 "false" 不再被当真值
- #21：壁纸文件服务被拒绝路径返回 403（不再被 except Exception 吞成 404），正常图片 200

说明：
- 测试客户端默认 UA 为 werkzeug，会被 ipguard 第一防线识别为未知浏览器限流，
  故所有请求统一携带真实浏览器 UA（Chrome）。
- 未登录 401 分支测试沿用 test_setup.py 的既有模式临时移除 authentication_check 中间件
  （全局认证中间件会先把未登录请求重定向到登录页，路由级分支不可直达）。
"""

import json
import shutil
from pathlib import Path

import pytest

from Module.common import user_utils


CSRF_TOKEN = "test-csrf-token"

# 真实浏览器 UA（Chrome/Windows），避免 ipguard 第一防线按未知 UA 限流
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

REPO_ROOT = Path(__file__).resolve().parents[1]

# 壁纸文件服务 200 测试使用的固定目录（位于仓库根内以满足沙箱检查，测试后清理）
WALLPAPER_FIXTURE_DIR = "wallpaper_c3_fixture"


def _headers(**extra):
    base = {"X-CSRF-Token": CSRF_TOKEN, "User-Agent": BROWSER_UA}
    base.update(extra)
    return base


@pytest.fixture
def config_file(tmp_path, monkeypatch):
    """将 index 模块的 config.json 重定向到临时文件，避免写生产配置"""
    target = tmp_path / "config.json"
    target.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("Module.common.config_utils.CONFIG_FILE", target)
    return target


@pytest.fixture
def wallpaper_fixture_dir():
    """在仓库根内创建含一张 png 的壁纸目录（沙箱要求路径在项目根内），测试后清理"""
    d = REPO_ROOT / WALLPAPER_FIXTURE_DIR
    d.mkdir(exist_ok=True)
    (d / "a.png").write_bytes(b"fake-png")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def no_auth_middleware(app):
    """临时移除全局认证中间件，使未登录请求可直达路由自身的 401 分支"""
    before_funcs = app.before_request_funcs.get(None, [])
    original = list(before_funcs)
    app.before_request_funcs[None] = [
        f for f in before_funcs if getattr(f, "__name__", "") != "authentication_check"
    ]
    yield
    app.before_request_funcs[None] = original


def _login(client, user_id, username, role, verified=True):
    user_utils.save_users(
        {
            username: {
                "id": user_id,
                "username": username,
                "password": "pass123",
                "role": role,
                "enabled": True,
            },
        }
    )
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["username"] = username
        sess["role"] = role
        sess["verified"] = verified
        sess["csrf_token"] = CSRF_TOKEN


def _login_superadmin(client, verified=True):
    _login(client, 0, "admin", "admin", verified=verified)


def _post_wallpaper(client, payload):
    return client.post(
        "/api/wallpaper/config", json=payload, headers=_headers()
    )


def _read_wallpaper_config(config_file):
    return json.loads(config_file.read_text(encoding="utf-8"))


class TestPermission:
    """POST /api/wallpaper/config 权限体系（bug #20 主修复）"""

    def test_unauthenticated_401(self, client, app, config_file, no_auth_middleware):
        """未登录：路由自身返回 401 JSON（与该接口既有语义一致）"""
        with client.session_transaction() as sess:
            sess["csrf_token"] = CSRF_TOKEN
        resp = _post_wallpaper(client, {"enabled": True})
        assert resp.status_code == 401
        data = resp.get_json()
        assert data["success"] is False
        assert "登录" in data["message"]

    def test_normal_user_403(self, client, app, config_file):
        """普通登录用户：403 JSON（response.py 统一格式），配置不被修改"""
        _login(client, 99, "alice", "user")
        resp = _post_wallpaper(client, {"enabled": True})
        assert resp.status_code == 403
        data = resp.get_json()
        assert data["code"] == 403
        assert data["data"] is None
        assert "超级管理员" in data["msg"]
        assert "enabled" not in _read_wallpaper_config(config_file)

    def test_superadmin_unverified_redirects_to_verify(self, client, app, config_file):
        """超管未过二次验证：与 admin 模块一致重定向验证页"""
        _login_superadmin(client, verified=False)
        resp = _post_wallpaper(client, {"enabled": True})
        assert resp.status_code == 302
        assert resp.location.endswith("/user/verify")
        assert "enabled" not in _read_wallpaper_config(config_file)

    def test_superadmin_200_and_config_applied(self, client, app, config_file):
        """超管（已验证）：200 且配置生效"""
        _login_superadmin(client, verified=True)
        resp = _post_wallpaper(client, {"enabled": True})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert _read_wallpaper_config(config_file)["wallpaper"]["enabled"] is True


class TestEnabledCoercion:
    """enabled 强转（bug #20 伴随修复）"""

    def test_boolean_false_stays_false(self, client, app, config_file):
        """布尔 False（前端实际发送形态）：落库为 False"""
        _login_superadmin(client)
        resp = _post_wallpaper(client, {"enabled": False})
        assert resp.status_code == 200
        assert _read_wallpaper_config(config_file)["wallpaper"]["enabled"] is False

    def test_string_false_becomes_false(self, client, app, config_file):
        """字符串 "false"：不再被当真值（修复点）"""
        _login_superadmin(client)
        resp = _post_wallpaper(client, {"enabled": "false"})
        assert resp.status_code == 200
        assert _read_wallpaper_config(config_file)["wallpaper"]["enabled"] is False

    def test_string_true_becomes_true(self, client, app, config_file):
        """字符串 "true"：映射为 True"""
        _login_superadmin(client)
        resp = _post_wallpaper(client, {"enabled": "true"})
        assert resp.status_code == 200
        assert _read_wallpaper_config(config_file)["wallpaper"]["enabled"] is True


class TestServeWallpaperHttpException:
    """壁纸文件服务 HTTPException 透传（bug #21）"""

    def test_rejected_path_returns_403(self, client, app, config_file):
        """路径逃逸项目根：403 直接透传（修复前被 except Exception 吞成 404）"""
        config_file.write_text(
            json.dumps({"wallpaper": {"enabled": True, "path": "C:/Windows"}}),
            encoding="utf-8",
        )
        resp = client.get("/static/wallpaper", headers=_headers())
        assert resp.status_code == 403

    def test_normal_image_returns_200(
        self, client, app, config_file, wallpaper_fixture_dir
    ):
        """项目根内正常图片目录：200 且 Content-Type 为图片"""
        config_file.write_text(
            json.dumps(
                {"wallpaper": {"enabled": True, "path": WALLPAPER_FIXTURE_DIR}}
            ),
            encoding="utf-8",
        )
        resp = client.get("/static/wallpaper", headers=_headers())
        assert resp.status_code == 200
        assert resp.headers["Content-Type"].startswith("image/")

    def test_disabled_returns_404(self, client, app, config_file):
        """壁纸未启用：404 正常透传"""
        resp = client.get("/static/wallpaper", headers=_headers())
        assert resp.status_code == 404


class TestGetNoPathLeak:
    """GET /api/wallpaper/config 不回显原始服务器路径（最终审查 I3，ADR-0001）

    该接口虽定位为公开只读（首页渲染用），但认证中间件会先把匿名请求重定向，
    实际可达者为所有登录用户（含普通用户）——故以普通登录用户视角断言不泄露。
    """

    def test_disabled_with_path_masks_path(self, client, app, config_file):
        """功能关闭但已配置原始路径：响应 path 为空串且不含原始路径"""
        _login(client, 99, "alice", "user")
        config_file.write_text(
            json.dumps(
                {"wallpaper": {"enabled": False, "path": "secret/wallpaper_dir"}}
            ),
            encoding="utf-8",
        )
        resp = client.get("/api/wallpaper/config", headers=_headers())
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["enabled"] is False
        assert data["path"] == ""
        # 原始路径字符串不得出现在响应体的任何位置
        assert "secret/wallpaper_dir" not in resp.get_data(as_text=True)

    def test_enabled_returns_public_route(self, client, app, config_file):
        """功能开启且已配置路径：仅回显公开静态路由，不回显原始路径"""
        _login(client, 99, "alice", "user")
        config_file.write_text(
            json.dumps(
                {"wallpaper": {"enabled": True, "path": "secret/wallpaper_dir"}}
            ),
            encoding="utf-8",
        )
        resp = client.get("/api/wallpaper/config", headers=_headers())
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["enabled"] is True
        assert data["path"] == "/static/wallpaper"
        assert "secret/wallpaper_dir" not in resp.get_data(as_text=True)

    def test_feature_disabled_masks_path(self, client, app, config_file):
        """功能开关关闭：既有的 path="" 兜底行为不回归"""
        _login(client, 99, "alice", "user")
        config_file.write_text(
            json.dumps({"wallpaper": {"enabled": False, "path": ""}}),
            encoding="utf-8",
        )
        resp = client.get("/api/wallpaper/config", headers=_headers())
        assert resp.status_code == 200
        assert resp.get_json()["path"] == ""


class TestGenericErrorMessages:
    """三处 except 分支不再回显 str(e)，改为通用文案 + 日志（最终审查 I3，ADR-0001）"""

    def test_get_generic_message_and_logged(
        self, client, app, config_file, monkeypatch, caplog
    ):
        """GET 接口异常：响应为通用文案、不含异常原文，原始异常已记录日志"""
        _login(client, 99, "alice", "user")

        def boom(ttl=5):
            raise RuntimeError("敏感内部信息 E:\\data\\secret")

        monkeypatch.setattr("Module.index.index.load_config", boom)
        with caplog.at_level("ERROR", logger="Module.index.index"):
            resp = client.get("/api/wallpaper/config", headers=_headers())
        data = resp.get_json()
        assert data["success"] is False
        assert data["message"] == "服务器内部错误，请查看日志"
        assert "敏感内部信息" not in resp.get_data(as_text=True)
        assert "获取壁纸配置失败" in caplog.text
        assert "敏感内部信息" in caplog.text

    def test_post_generic_message_and_logged(
        self, client, app, config_file, monkeypatch, caplog
    ):
        """POST 接口异常（已过超管鉴权）：响应为通用文案且已记录日志（C3 鉴权不回归）"""
        _login_superadmin(client, verified=True)

        def boom(ttl=5):
            raise RuntimeError("敏感内部信息 E:\\data\\secret")

        monkeypatch.setattr("Module.index.index.load_config", boom)
        with caplog.at_level("ERROR", logger="Module.index.index"):
            resp = _post_wallpaper(client, {"enabled": True})
        data = resp.get_json()
        assert data["success"] is False
        assert data["message"] == "服务器内部错误，请查看日志"
        assert "敏感内部信息" not in resp.get_data(as_text=True)
        assert "更新壁纸配置失败" in caplog.text

    def test_mounted_pages_generic_message_and_logged(
        self, client, app, config_file, monkeypatch, caplog
    ):
        """公开挂载列表接口异常：响应为通用文案且已记录日志"""
        _login(client, 99, "alice", "user")

        def boom(ttl=5):
            raise RuntimeError("敏感内部信息 E:\\data\\secret")

        monkeypatch.setattr("Module.index.index.load_config", boom)
        with caplog.at_level("ERROR", logger="Module.index.index"):
            resp = client.get("/api/mounted-pages", headers=_headers())
        data = resp.get_json()
        assert data["success"] is False
        assert data["message"] == "服务器内部错误，请查看日志"
        assert "敏感内部信息" not in resp.get_data(as_text=True)
        assert "获取挂载页面列表失败" in caplog.text
