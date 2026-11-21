"""
管理后台用户管理路由
"""

from flask import Blueprint, render_template, session, request, jsonify
from Module.core.admin_service import AdminService
from Module.common.user_utils import require_superadmin, add_activity

admin_users_bp = Blueprint(
    "admin_users", __name__, url_prefix="/admin", template_folder="templates"
)
_service = AdminService()


@admin_users_bp.route("/users")
def users_page():
    check = require_superadmin()
    if check:
        return check
    all_users = _service.get_user_list()
    active_sessions = _service.get_active_sessions()
    active_users = []
    for u in all_users:
        if u["username"] in active_sessions:
            s = active_sessions[u["username"]]
            active_users.append(
                {
                    "username": u["username"],
                    "role": u["role"],
                    "ip": s.get("ip", ""),
                    "user_agent": s.get("user_agent", ""),
                    "last_activity": s.get("last_activity", ""),
                }
            )
    return render_template(
        "admin/users.html", all_users=all_users, active_users=active_users
    )


@admin_users_bp.route("/users/<username>/toggle", methods=["POST"])
def toggle_user_status(username):
    check = require_superadmin()
    if check:
        return check
    current_username = session.get("username")
    success, message = _service.toggle_user_status(username, current_username)
    return jsonify({"success": success, "message": message})


@admin_users_bp.route("/users/register", methods=["POST"])
def register_user():
    check = require_superadmin()
    if check:
        return check
    data = request.get_json()
    username = data.get("username", "").strip()
    password = data.get("password", "")
    role = data.get("role", "user")
    uid = data.get("uid")
    if uid in ("", None):
        uid = None
    if not username or not password:
        return jsonify({"success": False, "message": "用户名和密码不能为空"})
    success, message = _service.register_user(username, password, role, uid)
    if success:
        add_activity(
            username=session.get("username"),
            description=f"注册新用户：{username}",
            ip=_service.get_real_ip(request),
            path=request.path,
            user_agent=request.user_agent.string,
            is_logged_in=True,
        )
    return jsonify({"success": success, "message": message})


@admin_users_bp.route("/users/<username>/delete", methods=["POST"])
def delete_user(username):
    check = require_superadmin()
    if check:
        return check
    current_username = session.get("username")
    success, message = _service.delete_user(username, current_username)
    if success:
        add_activity(
            username=current_username,
            description=f"删除用户：{username}",
            ip=_service.get_real_ip(request),
            path=request.path,
            user_agent=request.user_agent.string,
            is_logged_in=True,
        )
    return jsonify({"success": success, "message": message})
