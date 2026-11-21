"""
管理后台活动日志路由
"""

import math

from flask import Blueprint, render_template, request, jsonify, session
from Module.core.admin_service import AdminService
from Module.common.user_utils import (
    require_superadmin,
    load_activities,
    save_activities,
    add_activity,
)
from Module.common.security import generate_csrf_token

admin_activity_bp = Blueprint(
    "admin_activity", __name__, url_prefix="/admin", template_folder="templates"
)
_service = AdminService()


@admin_activity_bp.route("/activity")
def activity():
    check = require_superadmin()
    if check:
        return check
    activities = load_activities()
    return render_template("admin/activity.html", activities=activities)


@admin_activity_bp.route("/activity/all")
def activity_all():
    check = require_superadmin()
    if check:
        return check
    return render_template("admin/activity_all.html")


def _group_activities(activities):
    """
    将活动记录聚合为折叠分组结构

    聚合键为 (username, description, path)：同一账号在同一页面执行同类操作的
    多次访问折叠为一组，展示最新时间（latest_time）与访问次数（count）。
    activities 必须按"最新在前"顺序传入（load_activities 的天然顺序），
    分组结果亦按最新活动排序。

    Returns:
        list[dict]: 每项包含 is_group（count>1 时为 True，前端据此渲染折叠行；
        count==1 时前端直接读取 activities[0] 渲染普通行）、username、
        description、ip、device_type、os、browser、path、is_logged_in、
        latest_time、count、activities（组内完整记录列表，最新在前）。
    """
    groups = {}
    order = []
    for a in activities:
        key = (a.get("username", ""), a.get("description", ""), a.get("path", ""))
        if key not in groups:
            order.append(key)
            groups[key] = {
                "is_group": False,
                "username": a.get("username", ""),
                "description": a.get("description", ""),
                "ip": a.get("ip", ""),
                "device_type": a.get("device_type", ""),
                "os": a.get("os", ""),
                "browser": a.get("browser", ""),
                "path": a.get("path", ""),
                "is_logged_in": bool(a.get("is_logged_in", False)),
                "latest_time": a.get("time", ""),
                "count": 0,
                "activities": [],
            }
        group = groups[key]
        group["count"] += 1
        group["activities"].append(a)
    result = [groups[k] for k in order]
    # count > 1 折叠展示；count == 1 由前端直接读取 activities[0] 渲染普通行
    for group in result:
        group["is_group"] = group["count"] > 1
    return result


def _slice_page(items, page, per_page):
    """按页截取列表（页码/每页数量越界时钳制到有效范围）"""
    page = max(1, page)
    per_page = max(1, per_page)
    start = (page - 1) * per_page
    return items[start : start + per_page], page, per_page


@admin_activity_bp.route("/activity/api")
def activity_api():
    check = require_superadmin()
    if check:
        return check
    show_all = request.args.get("show_all", "false") == "true"
    grouped = request.args.get("grouped", "false") == "true"
    username = request.args.get("username", "").strip()
    users_only = request.args.get("users_only", "") in ("true", "1")
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 200, type=int)
    # 显式携带 page/per_page 的调用方（activity_all 页）走真实分页；
    # activity 页不传这两个参数，仅按默认 per_page（200，与"最近200条"标题对齐）截取；
    # show_all 且未显式分页时返回全量（保持原有行为）
    paginate = "page" in request.args or "per_page" in request.args
    activities = load_activities()

    # 轻量用户列表：全量去重的已登录用户名，供筛选按钮使用，
    # 不再依赖当前页的 200 条切片
    if users_only:
        users = sorted(
            {
                a.get("username", "")
                for a in activities
                if a.get("is_logged_in") and a.get("username") not in ("", "未登录")
            }
        )
        return jsonify({"success": True, "users": users})

    if username:
        activities = [a for a in activities if a.get("username", "") == username]

    total = len(activities)

    if grouped:
        if not paginate and not show_all:
            # 未显式分页且非 show_all：先按默认 per_page（200，与"最近200条"
            # 标题对齐）截取最新记录再分组，与平铺模式行为一致
            activities = _slice_page(activities, page, per_page)[0]
        groups = _group_activities(activities)
        total_groups = len(groups)
        if paginate:
            groups, page, per_page = _slice_page(groups, page, per_page)
            total_pages = max(1, math.ceil(total_groups / per_page))
        else:
            total_pages = 1
        return jsonify(
            {
                "success": True,
                "activities": groups,
                "grouped": True,
                "total": total,
                "total_groups": total_groups,
                "page": page,
                "per_page": per_page,
                "total_pages": total_pages,
            }
        )

    # 平铺模式：在原响应结构基础上仅追加 grouped/total_pages 字段，向后兼容
    if paginate:
        result, page, per_page = _slice_page(activities, page, per_page)
        total_pages = max(1, math.ceil(total / per_page))
    elif show_all:
        result = activities
        total_pages = 1
    else:
        result, page, per_page = _slice_page(activities, page, per_page)
        total_pages = 1
    return jsonify(
        {
            "success": True,
            "activities": result,
            "grouped": False,
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages,
        }
    )


@admin_activity_bp.route("/activity/api/cleanup", methods=["POST"])
def cleanup_activities():
    """清理指定天数之前的活动日志"""
    check = require_superadmin()
    if check:
        return check
    data = request.get_json()
    if not data or "days" not in data:
        return jsonify({"success": False, "message": "缺少参数"})
    days = data.get("days")
    if not isinstance(days, int) or days <= 0:
        return jsonify({"success": False, "message": "无效的天数"})
    from datetime import datetime, timedelta

    cutoff = datetime.now() - timedelta(days=days)
    activities = load_activities()
    original_count = len(activities)
    
    def parse_time(time_str):
        """解析时间字符串，返回datetime对象"""
        try:
            return datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            # 无法解析的时间视为"刚刚发生"：保留记录不参与清理（bug #24，
            # 原先返回 datetime.min 会被当作最早时间而误删）
            return datetime.now()
    
    filtered = [a for a in activities if parse_time(a.get("time", "")) > cutoff]
    deleted_count = original_count - len(filtered)
    save_activities(filtered)
    add_activity(
        username=session.get("username"),
        description=f"清理{days}天前的活动日志，共删除{deleted_count}条记录",
        ip=_service.get_real_ip(request),
        path=request.path,
        user_agent=request.user_agent.string,
        is_logged_in=True,
    )
    return jsonify({"success": True, "deleted_count": deleted_count})
