"""
活动日志 API 分组折叠与用户筛选测试（bug #2 + #5 回归）

背景：/admin/activity/api 原先只读 show_all/page/per_page，从不读取前端
传来的 grouped/username 参数，恒返回平铺切片，导致 activity.html 的
折叠分支与用户筛选永不生效；/admin/activity/all 渲染 activity.html 而
activity_all.html（完整分组+分页逻辑）调用不存在的 /admin/activity/api/all。
"""

from pathlib import Path

import pytest

from Module.common import user_utils

TEMPLATE_DIR = (
    Path(__file__).resolve().parent.parent / "Module" / "admin" / "templates" / "admin"
)
ACTIVITY_HTML = TEMPLATE_DIR / "activity.html"
ACTIVITY_ALL_HTML = TEMPLATE_DIR / "activity_all.html"


# ============================================================================
# 辅助
# ============================================================================


def _create_admin_and_login(client, app, username="admin", user_id=0, verified=True):
    """创建超级管理员并注入登录态（参考 test_integration.py 同名辅助）"""
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


def _act(
    username,
    description,
    time,
    path,
    ip="1.2.3.4",
    is_logged_in=True,
    device_type="Windows",
    os_name="Windows 10/11",
    browser="Chrome",
):
    """构造一条活动记录（字段与 activity_log 表一致）"""
    return {
        "username": username if is_logged_in else "未登录",
        "description": description,
        "time": time,
        "ip": ip,
        "path": path,
        "device_type": device_type,
        "os": os_name,
        "browser": browser,
        "is_logged_in": is_logged_in,
    }


@pytest.fixture
def seeded_activities():
    """
    预置活动数据（按时间从旧到新排列，save_activities 按此顺序入库）：
    - alice 在 /user/login 的"用户登录" 3 次（应折叠为一组，count=3）
    - alice 在 /gallery 的"查看画廊" 1 次（count=1，普通行）
    - 未登录在 / 的"访问首页" 2 次（应折叠为一组，count=2）
    - bob 在 /user/login 的"用户登录" 1 次（count=1）
    """
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


# ============================================================================
# 权限
# ============================================================================


def test_api_requires_superadmin(client, app):
    """未登录访问活动日志 API 重定向到登录页"""
    resp = client.get("/admin/activity/api")
    assert resp.status_code == 302
    assert resp.location.endswith("/login")


# ============================================================================
# 平铺模式（向后兼容）
# ============================================================================


def test_flat_default_response_backward_compatible(client, app, seeded_activities):
    """grouped=false 平铺结构与原响应兼容，仅追加 grouped/total_pages 字段"""
    _create_admin_and_login(client, app)
    resp = client.get("/admin/activity/api?grouped=false")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["grouped"] is False
    assert data["total"] == 7
    assert data["page"] == 1
    assert data["per_page"] == 200
    # 平铺返回的是原始记录（顶层含 time，不含分组字段）
    assert len(data["activities"]) == 7
    first = data["activities"][0]
    assert "time" in first
    assert "is_group" not in first
    # 最新在前：首条应为 bob 2026-11-06
    assert first["username"] == "bob"
    assert first["time"] == "2026-11-06 09:00:00"


def test_flat_default_per_page_is_200(client, app):
    """默认 per_page=200，与页面标题"最近200条"对齐（原为 50）"""
    records = [
        _act("alice", "用户登录", f"2026-11-01 09:{i // 60:02d}:{i % 60:02d}", "/user/login")
        for i in range(250)
    ]
    user_utils.save_activities(records)
    _create_admin_and_login(client, app)
    resp = client.get("/admin/activity/api")
    data = resp.get_json()
    assert data["per_page"] == 200
    assert len(data["activities"]) == 200
    assert data["total"] == 250


def test_flat_username_filter(client, app, seeded_activities):
    """username 过滤在平铺模式下生效"""
    _create_admin_and_login(client, app)
    resp = client.get("/admin/activity/api?grouped=false&username=alice")
    data = resp.get_json()
    assert data["success"] is True
    assert data["total"] == 4
    assert all(a["username"] == "alice" for a in data["activities"])


def test_flat_show_all_returns_everything(client, app, seeded_activities):
    """show_all=true 且未显式分页时返回全量（保持原有行为）"""
    _create_admin_and_login(client, app)
    resp = client.get("/admin/activity/api?grouped=false&show_all=true")
    data = resp.get_json()
    assert len(data["activities"]) == 7
    assert data["total"] == 7


def test_flat_pagination_explicit(client, app, seeded_activities):
    """显式 page/per_page 走真实分页（activity_all 页场景）"""
    _create_admin_and_login(client, app)
    resp = client.get(
        "/admin/activity/api?grouped=false&show_all=true&page=2&per_page=3"
    )
    data = resp.get_json()
    assert data["page"] == 2
    assert data["per_page"] == 3
    assert data["total"] == 7
    assert data["total_pages"] == 3
    assert len(data["activities"]) == 3


# ============================================================================
# 分组模式
# ============================================================================


def test_grouped_structure_and_counts(client, app, seeded_activities):
    """grouped=true 返回折叠分组结构与计数"""
    _create_admin_and_login(client, app)
    resp = client.get("/admin/activity/api?grouped=true")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["grouped"] is True
    assert data["total"] == 7
    assert data["total_groups"] == 4

    groups = data["activities"]
    assert len(groups) == 4

    # alice 登录组：count=3，折叠行
    alice_login = next(
        g for g in groups if g["username"] == "alice" and g["path"] == "/user/login"
    )
    assert alice_login["is_group"] is True
    assert alice_login["count"] == 3
    assert alice_login["latest_time"] == "2026-11-04 09:00:00"
    assert alice_login["is_logged_in"] is True
    assert len(alice_login["activities"]) == 3
    # 组内记录最新在前，且为完整记录
    assert alice_login["activities"][0]["time"] == "2026-11-04 09:00:00"
    assert alice_login["activities"][0]["ip"] == "1.2.3.4"

    # 未登录组：count=2，username 为"未登录"
    anon_group = next(g for g in groups if g["username"] == "未登录")
    assert anon_group["is_group"] is True
    assert anon_group["count"] == 2
    assert anon_group["is_logged_in"] is False
    assert anon_group["latest_time"] == "2026-11-05 08:00:00"

    # count=1 的组：is_group=False，前端直接读 activities[0]
    alice_gallery = next(
        g for g in groups if g["username"] == "alice" and g["path"] == "/gallery"
    )
    assert alice_gallery["is_group"] is False
    assert alice_gallery["count"] == 1
    assert alice_gallery["activities"][0]["time"] == "2026-11-03 10:00:00"

    # 分组按最新活动排序：首个分组应为最新一条（bob）
    assert groups[0]["username"] == "bob"
    assert groups[0]["latest_time"] == "2026-11-06 09:00:00"


def test_grouped_username_filter_not_logged_in(client, app, seeded_activities):
    """点击"未登录访问"按钮（username=未登录）能过滤出未登录记录"""
    _create_admin_and_login(client, app)
    resp = client.get("/admin/activity/api?grouped=true&username=未登录")
    data = resp.get_json()
    assert data["success"] is True
    assert data["total"] == 2
    assert data["total_groups"] == 1
    assert len(data["activities"]) == 1
    group = data["activities"][0]
    assert group["username"] == "未登录"
    assert group["count"] == 2
    assert group["is_group"] is True


def test_grouped_pagination_with_show_all(client, app, seeded_activities):
    """activity_all 页场景：show_all=true + 显式分页，按组分页"""
    _create_admin_and_login(client, app)
    resp = client.get(
        "/admin/activity/api?grouped=true&show_all=true&page=1&per_page=2"
    )
    data = resp.get_json()
    assert data["grouped"] is True
    assert data["total_groups"] == 4
    assert data["total_pages"] == 2
    assert data["page"] == 1
    assert len(data["activities"]) == 2
    # 每组仍带完整 activities 子列表
    assert all(len(g["activities"]) >= 1 for g in data["activities"])


def test_grouped_default_sliced_to_200(client, app):
    """
    分组模式未显式分页时同样截取最新 200 条再分组（修复轮 1，I-1）

    activity 页折叠模式实际调用形态是 grouped=true 且不传 page/per_page，
    必须与平铺模式及"最近200条"标题对齐；show_all=true 时不受默认切片限制。
    """
    # bob 1 条最旧记录 + alice 同一操作 250 条（时间递增）
    records = [_act("bob", "用户登录", "2026-10-01 00:00:00", "/user/login")]
    records += [
        _act(
            "alice",
            "用户登录",
            "2026-11-%02d %02d:00:00" % (1 + i // 24, i % 24),
            "/user/login",
        )
        for i in range(250)
    ]
    user_utils.save_activities(records)
    _create_admin_and_login(client, app)

    # 默认（无 page/per_page、非 show_all）：分组只包含最新 200 条
    resp = client.get("/admin/activity/api?grouped=true")
    data = resp.get_json()
    assert data["success"] is True
    assert data["total"] == 251  # 过滤后总数不受默认切片影响
    assert data["total_groups"] == 1  # bob 与最旧 50 条 alice 已被截去
    assert len(data["activities"]) == 1
    group = data["activities"][0]
    assert group["username"] == "alice"
    assert group["count"] == 200
    assert len(group["activities"]) == 200
    assert group["latest_time"] == "2026-11-11 09:00:00"  # i=249 的最新记录
    assert group["activities"][0]["time"] == "2026-11-11 09:00:00"

    # show_all=true：分组不受默认切片限制，全量分组
    resp_all = client.get("/admin/activity/api?grouped=true&show_all=true")
    data_all = resp_all.get_json()
    assert data_all["total"] == 251
    assert data_all["total_groups"] == 2
    alice_all = next(
        g for g in data_all["activities"] if g["username"] == "alice"
    )
    assert alice_all["count"] == 250


# ============================================================================
# 轻量用户列表（users_only）
# ============================================================================


def test_users_only_full_dedup_list(client, app, seeded_activities):
    """users_only=1 返回全量去重的已登录用户名（不依赖当前页切片，排除未登录）"""
    _create_admin_and_login(client, app)
    resp = client.get("/admin/activity/api?users_only=1")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["users"] == ["alice", "bob"]
    assert "未登录" not in data["users"]


def test_users_only_independent_of_pagination(client, app):
    """即使部分用户不在默认 200 条切片内，users_only 仍能列出全部用户"""
    records = [
        _act("alice", "用户登录", "2026-11-01 09:00:00", "/user/login"),
    ] + [
        _act("zoe", "查看画廊", "2026-11-02 09:%02d:00" % i, "/gallery")
        for i in range(250)
    ]
    user_utils.save_activities(records)
    _create_admin_and_login(client, app)
    resp = client.get("/admin/activity/api?users_only=1")
    data = resp.get_json()
    assert data["users"] == ["alice", "zoe"]


# ============================================================================
# /admin/activity/all 页面路由（bug #5）
# ============================================================================


def test_activity_all_page_renders_activity_all_template(client, app):
    """/admin/activity/all 现渲染 activity_all.html（原渲染 activity.html）"""
    _create_admin_and_login(client, app)
    resp = client.get("/admin/activity/all")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    # activity_all.html 独有特征
    assert "全量活动日志" in html
    assert 'id="pagination"' in html
    # 复用统一 API 并携带 show_all=true
    assert "/admin/activity/api?show_all=true" in html
    # 不再调用不存在的端点
    assert "/admin/activity/api/all" not in html


# ============================================================================
# 模板接线回归（字符串级）
# ============================================================================


def test_activity_html_uses_users_only_endpoint():
    """activity.html 的 loadUserList 改用 users_only 轻量参数"""
    source = ACTIVITY_HTML.read_text(encoding="utf-8")
    assert "users_only=1" in source
    assert "data.users" in source


def test_activity_all_html_uses_shared_api():
    """activity_all.html 不再调用不存在的 /admin/activity/api/all"""
    source = ACTIVITY_ALL_HTML.read_text(encoding="utf-8")
    assert "/admin/activity/api/all" not in source
    assert "/admin/activity/api?show_all=true" in source
    assert "users_only=1" in source


def test_both_templates_keep_escape_html():
    """安全审计回归：两个模板的 escapeHtml 转义函数必须保留"""
    for path in (ACTIVITY_HTML, ACTIVITY_ALL_HTML):
        source = path.read_text(encoding="utf-8")
        assert "function escapeHtml(" in source, f"{path.name} 缺少 escapeHtml"
