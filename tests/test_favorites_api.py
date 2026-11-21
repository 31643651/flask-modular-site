"""
画廊收藏 API 错误状态码统一测试（bug #14）

- check_favorite 未登录返回 401（与其余收藏 API 口径一致）
- add/remove 参数错误（空路径）返回 400
- 已登录正常收藏 / 重复收藏 / 取消收藏 / 查询行为不回归

说明：
- 测试客户端默认 UA 为 werkzeug，会被 ipguard 第一防线识别为未知浏览器限流，
  故所有请求统一携带真实浏览器 UA（Chrome）。
- 全局认证中间件会把未登录请求先重定向到登录页，路由级未登录 401 分支不可直达，
  因此该分支测试沿用 test_setup.py 的既有模式临时移除 authentication_check 中间件。
"""

import pytest

from Module.common import user_utils


CSRF_TOKEN = "test-csrf-token"

# 真实浏览器 UA（Chrome/Windows），避免 ipguard 第一防线按未知 UA 限流
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def _headers(**extra):
    base = {"X-CSRF-Token": CSRF_TOKEN, "User-Agent": BROWSER_UA}
    base.update(extra)
    return base


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


@pytest.fixture
def logged_in(client, app):
    """创建用户并注入登录态与 CSRF token"""
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
        sess["csrf_token"] = CSRF_TOKEN


class TestCheckFavoriteUnauthenticated:
    """未登录 check_favorite 必须与其余收藏 API 一致返回 401"""

    def test_check_favorite_unauthenticated_401(self, client, app, no_auth_middleware):
        """未登录（session 有 csrf_token 但无 user_id）：401 且 success=False"""
        with client.session_transaction() as sess:
            sess["csrf_token"] = CSRF_TOKEN
        resp = client.post(
            "/gallery/api/favorite/check",
            json={"path": "img/a.jpg"},
            headers=_headers(),
        )
        assert resp.status_code == 401
        data = resp.get_json()
        assert data["success"] is False
        assert "未登录" in data["message"]

    def test_get_favorites_unauthenticated_401(self, client, app, no_auth_middleware):
        """未登录获取收藏列表：401（既有口径不回归）"""
        resp = client.get("/gallery/api/favorites", headers=_headers())
        assert resp.status_code == 401


class TestParamErrors:
    """收藏增删参数错误统一返回 400"""

    def test_add_empty_path_400(self, client, app, logged_in):
        """add 空路径：400"""
        resp = client.post(
            "/gallery/api/favorite/add",
            json={"path": "   "},
            headers=_headers(),
        )
        assert resp.status_code == 400
        assert resp.get_json()["success"] is False

    def test_remove_missing_path_400(self, client, app, logged_in):
        """remove 缺少 path 字段：400"""
        resp = client.post(
            "/gallery/api/favorite/remove",
            json={},
            headers=_headers(),
        )
        assert resp.status_code == 400
        assert resp.get_json()["success"] is False


class TestNormalFavoriteFlow:
    """已登录正常收藏行为不回归"""

    def test_add_and_check(self, client, app, logged_in):
        """收藏后查询为真，重复收藏幂等"""
        # 收藏（反斜杠路径，服务端归一化为正斜杠）
        resp = client.post(
            "/gallery/api/favorite/add",
            json={"path": "vacation\\a.jpg"},
            headers=_headers(),
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["message"] == "已添加收藏"

        # 查询（归一化后同一路径）
        resp = client.post(
            "/gallery/api/favorite/check",
            json={"path": "vacation/a.jpg"},
            headers=_headers(),
        )
        assert resp.status_code == 200
        assert resp.get_json()["is_favorite"] is True

        # 收藏列表可见
        resp = client.get("/gallery/api/favorites", headers=_headers())
        assert resp.status_code == 200
        assert resp.get_json()["favorites"] == ["vacation/a.jpg"]

    def test_repeated_add_idempotent(self, client, app, logged_in):
        """重复收藏返回"已收藏"且不产生重复记录"""
        client.post(
            "/gallery/api/favorite/add",
            json={"path": "vacation/a.jpg"},
            headers=_headers(),
        )
        resp = client.post(
            "/gallery/api/favorite/add",
            json={"path": "vacation/a.jpg"},
            headers=_headers(),
        )
        assert resp.status_code == 200
        assert resp.get_json()["message"] == "已收藏"

        resp = client.get("/gallery/api/favorites", headers=_headers())
        assert resp.get_json()["favorites"] == ["vacation/a.jpg"]

    def test_remove_and_check(self, client, app, logged_in):
        """取消收藏后查询为假"""
        client.post(
            "/gallery/api/favorite/add",
            json={"path": "vacation/a.jpg"},
            headers=_headers(),
        )
        resp = client.post(
            "/gallery/api/favorite/remove",
            json={"path": "vacation/a.jpg"},
            headers=_headers(),
        )
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True

        resp = client.post(
            "/gallery/api/favorite/check",
            json={"path": "vacation/a.jpg"},
            headers=_headers(),
        )
        assert resp.status_code == 200
        assert resp.get_json()["is_favorite"] is False
