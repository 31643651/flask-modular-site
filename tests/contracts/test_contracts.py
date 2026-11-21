"""
契约测试：goldens 近似比较（D2）

规则：
- golden 描述"必需键 + 类型"（点号路径，"[]" 段展开为对列表逐元素校验）；
- 多余键允许；必需键缺失或类型不符即失败；
- 不做逐字节全文比对。

覆盖本次修复锚定的四个契约：
a. 活动日志 API /admin/activity/api：grouped=true 分组结构 与 grouped=false 平铺结构（B1）
b. 画廊偏好 /gallery/api/preferences：GET 读回结构（9 个默认键）与 POST 保存语义（B2）
c. 挂载页面添加 API：成功响应 {success, message, name, page_type, redirect_url}（B5）
d. 收藏 API 状态码矩阵：未登录 401、参数错误 400、成功 200（B6）

实现方式沿用既有做法：test client + 临时目录/临时库
（参考 tests/test_gallery_preferences.py、test_admin_mounted_pages.py、
test_admin_activity_api.py、test_favorites_api.py）。
"""

import json
from pathlib import Path

import pytest

from Module.common import user_utils


GOLDENS_DIR = Path(__file__).parent / "goldens"

CSRF_TOKEN = "test-csrf-token"

# 真实浏览器 UA（Chrome/Windows），避免 ipguard 第一防线按 werkzeug 默认 UA 限流
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def _headers(**extra):
    base = {"X-CSRF-Token": CSRF_TOKEN, "User-Agent": BROWSER_UA}
    base.update(extra)
    return base


# ============================================================================
# golden 加载与近似比较器
# ============================================================================


def _load_golden(name):
    return json.loads((GOLDENS_DIR / name).read_text(encoding="utf-8"))


class _PathNotFound(Exception):
    """点号路径在数据中解析不到对应键"""


_TYPES = {"bool": bool, "int": int, "str": str, "list": list, "dict": dict}


def _resolve(value, parts):
    """按路径段解析；以 '[]' 结尾的段先取键名再展开为对列表每个元素继续解析"""
    if not parts:
        return [value]
    head, rest = parts[0], parts[1:]
    if head == "[]" or head.endswith("[]"):
        key = head[:-2] if head != "[]" else None
        if key is None:
            if not isinstance(value, list):
                raise _PathNotFound
            items = value
        else:
            if not isinstance(value, dict) or key not in value:
                raise _PathNotFound
            items = value[key]
            if not isinstance(items, list):
                raise _PathNotFound
        matched = []
        for item in items:
            matched.extend(_resolve(item, rest))
        return matched
    if not isinstance(value, dict) or head not in value:
        raise _PathNotFound
    return _resolve(value[head], rest)


def assert_golden(data, golden, context):
    """校验 data 满足 golden 的 required 键类型图（多余键允许）"""
    for path, typ in golden["required"].items():
        try:
            values = _resolve(data, path.split("."))
        except _PathNotFound:
            pytest.fail(
                f"[{context}] 契约失败：缺少必需键 {path}（golden: {golden['description']}）"
            )
        for v in values:
            expected = _TYPES[typ]
            assert type(v) is expected, (
                f"[{context}] 契约失败：{path} 期望类型 {typ}，"
                f"实际 {type(v).__name__}（golden: {golden['description']}）"
            )


def assert_flat_schema(data, schema, context):
    """校验 dict 的顶层键类型（无点号路径的简单 schema）"""
    for key, typ in schema.items():
        assert key in data, (
            f"[{context}] 契约失败：缺少必需键 {key}"
        )
        expected = _TYPES[typ]
        assert type(data[key]) is expected, (
            f"[{context}] 契约失败：{key} 期望类型 {typ}，实际 {type(data[key]).__name__}"
        )


# ============================================================================
# 登录辅助与数据种子（复用既有 fixture 模式）
# ============================================================================


def _create_admin_and_login(client, app, username="admin", user_id=0, verified=True):
    """创建超级管理员并注入登录态"""
    user_utils.save_users(
        {
            username: {
                "id": user_id,
                "username": username,
                "password": "pass123",
                "role": "admin",
                "enabled": True,
            },
        }
    )
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["username"] = username
        sess["role"] = "admin"
        sess["verified"] = verified
        sess["csrf_token"] = CSRF_TOKEN


def _login_user(client, app, username="alice", user_id=99):
    """创建普通用户并注入登录态"""
    user_utils.save_users(
        {
            username: {
                "id": user_id,
                "username": username,
                "password": "pass123",
                "role": "user",
                "enabled": True,
            },
        }
    )
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["username"] = username
        sess["role"] = "user"
        sess["verified"] = True
        sess["csrf_token"] = CSRF_TOKEN


def _act(username, description, time, path, ip="1.2.3.4", is_logged_in=True):
    """构造一条活动记录（字段与 activity_log 表一致）"""
    return {
        "username": username if is_logged_in else "未登录",
        "description": description,
        "time": time,
        "ip": ip,
        "path": path,
        "device_type": "Windows",
        "os": "Windows 10/11",
        "browser": "Chrome",
        "is_logged_in": is_logged_in,
    }


@pytest.fixture
def seeded_activities():
    """预置活动数据：3 次登录折叠组 + 1 次普通行 + 未登录组"""
    records = [
        _act("alice", "用户登录", "2026-11-01 09:00:00", "/user/login"),
        _act("alice", "用户登录", "2026-11-02 09:00:00", "/user/login"),
        _act("未登录", "访问首页", "2026-11-03 08:00:00", "/", is_logged_in=False),
        _act("alice", "查看画廊", "2026-11-03 10:00:00", "/gallery"),
        _act("alice", "用户登录", "2026-11-04 09:00:00", "/user/login"),
        _act("未登录", "访问首页", "2026-11-05 08:00:00", "/", is_logged_in=False),
        _act("bob", "用户登录", "2026-11-06 09:00:00", "/user/login"),
    ]
    user_utils.save_activities(records)
    return records


@pytest.fixture
def prefs_file(tmp_path, monkeypatch):
    """将画廊偏好 JSON 重定向到临时文件，避免写生产 gallery_preferences.json"""
    target = tmp_path / "gallery_preferences.json"
    monkeypatch.setattr("Module.core.gallery_service.PREFERENCES_FILE", target)
    return target


@pytest.fixture
def config_file(tmp_path, monkeypatch):
    """将 config.json 重定向到临时文件，避免写生产配置"""
    target = tmp_path / "config.json"
    monkeypatch.setattr("Module.common.config_utils.CONFIG_FILE", target)
    return target


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


# ============================================================================
# 契约 a：活动日志 API（B1）
# ============================================================================


class TestActivityApiContract:
    def test_grouped_structure(self, client, app, seeded_activities):
        """grouped=true：分组折叠结构满足 golden，且折叠行为正确"""
        _create_admin_and_login(client, app)
        resp = client.get("/admin/activity/api?grouped=true", headers=_headers())
        assert resp.status_code == 200
        data = resp.get_json()

        assert_golden(data, _load_golden("admin_activity_api_grouped.json"), "grouped=true")

        # 行为锚定：alice 的 3 次登录折叠为一组，最新在前
        alice_login = next(
            g
            for g in data["activities"]
            if g["username"] == "alice" and g["path"] == "/user/login"
        )
        assert alice_login["is_group"] is True
        assert alice_login["count"] == 3
        assert alice_login["latest_time"] == "2026-11-04 09:00:00"
        assert len(alice_login["activities"]) == 3

    def test_flat_structure(self, client, app, seeded_activities):
        """grouped=false：平铺结构满足 golden，且默认 per_page=200 口径"""
        records = [
            _act("alice", "用户登录", f"2026-11-01 09:{i // 60:02d}:{i % 60:02d}", "/user/login")
            for i in range(250)
        ]
        user_utils.save_activities(records)
        _create_admin_and_login(client, app)
        resp = client.get("/admin/activity/api?grouped=false", headers=_headers())
        assert resp.status_code == 200
        data = resp.get_json()

        assert_golden(data, _load_golden("admin_activity_api_flat.json"), "grouped=false")

        assert data["per_page"] == 200
        assert len(data["activities"]) == 200
        assert data["total"] == 250


# ============================================================================
# 契约 b：画廊偏好（B2）
# ============================================================================


class TestGalleryPreferencesContract:
    def test_get_readback_structure(self, client, app, prefs_file):
        """GET 读回结构满足 golden（9 个默认键 + 类型）"""
        _login_user(client, app)
        resp = client.get("/gallery/api/preferences", headers=_headers())
        assert resp.status_code == 200
        data = resp.get_json()
        assert_golden(
            data, _load_golden("gallery_preferences_get.json"), "GET 读回"
        )

    def test_post_save_semantics(self, client, app, prefs_file):
        """POST 保存语义：保存后读回一致，未保存键回退默认值"""
        _login_user(client, app)
        resp = client.post(
            "/gallery/api/preferences",
            json={"preferences": {"discover_enabled": False}},
            headers=_headers(),
        )
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True

        resp = client.get("/gallery/api/preferences", headers=_headers())
        data = resp.get_json()
        assert data["preferences"]["discover_enabled"] is False
        assert data["preferences"]["image_quality"] == "high"

        # 裸字典形态兼容
        resp = client.post(
            "/gallery/api/preferences",
            json={"discover_format": "three"},
            headers=_headers(),
        )
        assert resp.get_json()["success"] is True
        data = client.get("/gallery/api/preferences", headers=_headers()).get_json()
        assert data["preferences"]["discover_format"] == "three"


# ============================================================================
# 契约 c：挂载页面添加 API（B5）
# ============================================================================


class TestMountedPageAddContract:
    def test_add_success_response(self, client, app, config_file):
        """添加成功响应满足 golden：五键结构与取值"""
        _create_admin_and_login(client, app)
        resp = client.post(
            "/admin/mounted-pages",
            json={"name": "docs", "path": "sdinspector/index.html"},
            headers=_headers(),
        )
        assert resp.status_code == 200
        data = resp.get_json()

        golden = _load_golden("admin_mounted_page_add.json")
        assert_golden(data, golden, "挂载页面添加")

        assert data["name"] == "docs"
        assert data["page_type"] == "file"
        assert data["redirect_url"] == "/docs"
        assert data["success"] is True

    def test_add_failure_response_has_no_redirect_fields(
        self, client, app, config_file
    ):
        """失败响应不携带 redirect_url/name/page_type（B5 锚定的失败分支）"""
        _create_admin_and_login(client, app)
        resp = client.post(
            "/admin/mounted-pages",
            json={"name": "", "path": ""},
            headers=_headers(),
        )
        data = resp.get_json()
        assert data["success"] is False
        assert "redirect_url" not in data
        assert "name" not in data


# ============================================================================
# 契约 d：收藏 API 状态码矩阵（B6）
# ============================================================================


class TestFavoritesStatusContract:
    def test_status_matrix(self, client, app, no_auth_middleware):
        """状态码矩阵：未登录 401、参数错误 400、成功 200，及成功响应体结构"""
        golden = _load_golden("gallery_favorites_status_codes.json")
        codes = golden["status_codes"]

        # 未登录（session 仅有 csrf_token，认证中间件已临时移除以直达路由分支）
        with client.session_transaction() as sess:
            sess["csrf_token"] = CSRF_TOKEN
        resp = client.post(
            "/gallery/api/favorite/check",
            json={"path": "a.jpg"},
            headers=_headers(),
        )
        assert resp.status_code == codes["check_unauthenticated"]
        resp = client.post(
            "/gallery/api/favorite/add", json={"path": "a.jpg"}, headers=_headers()
        )
        assert resp.status_code == codes["add_unauthenticated"]
        resp = client.post(
            "/gallery/api/favorite/remove", json={"path": "a.jpg"}, headers=_headers()
        )
        assert resp.status_code == codes["remove_unauthenticated"]

        # 登录后：参数错误 400
        _login_user(client, app)
        resp = client.post(
            "/gallery/api/favorite/add", json={"path": "   "}, headers=_headers()
        )
        assert resp.status_code == codes["add_empty_path"]
        resp = client.post(
            "/gallery/api/favorite/remove", json={}, headers=_headers()
        )
        assert resp.status_code == codes["remove_empty_path"]

        # 成功 200 + 响应体结构
        resp = client.post(
            "/gallery/api/favorite/add",
            json={"path": "vacation\\a.jpg"},
            headers=_headers(),
        )
        assert resp.status_code == codes["add_success"]
        assert_flat_schema(resp.get_json(), golden["mutate_success_body"], "add 成功体")

        resp = client.post(
            "/gallery/api/favorite/check",
            json={"path": "vacation/a.jpg"},
            headers=_headers(),
        )
        assert resp.status_code == codes["check_success"]
        check_body = resp.get_json()
        assert_flat_schema(check_body, golden["check_success_body"], "check 成功体")
        assert check_body["is_favorite"] is True

        resp = client.post(
            "/gallery/api/favorite/remove",
            json={"path": "vacation/a.jpg"},
            headers=_headers(),
        )
        assert resp.status_code == codes["remove_success"]
        assert_flat_schema(resp.get_json(), golden["mutate_success_body"], "remove 成功体")
