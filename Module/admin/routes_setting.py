"""
管理后台设置页面路由
"""

from flask import Blueprint, render_template, session, request, jsonify
from Module.core.admin_service import AdminService
from Module.common.user_utils import require_superadmin, add_activity
from Module.common.security import generate_csrf_token

admin_setting_bp = Blueprint(
    "admin_setting", __name__, url_prefix="/admin", template_folder="templates"
)
_service = AdminService()


@admin_setting_bp.route("/setting")
def setting_page():
    """设置页面"""
    check = require_superadmin()
    if check:
        return check
    server_info = _service.load_server_info()
    csrf_token = generate_csrf_token()
    return render_template(
        "admin/setting.html", server_info=server_info, csrf_token=csrf_token
    )


@admin_setting_bp.route("/setting/api")
def setting_api():
    """获取所有设置"""
    check = require_superadmin()
    if check:
        return check
    settings = _service.get_settings()
    return jsonify({"success": True, "settings": settings})


@admin_setting_bp.route("/setting/update", methods=["POST"])
def update_setting():
    """更新单个设置"""
    check = require_superadmin()
    if check:
        return check
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "message": "无效的请求数据"})
    key = data.get("key")
    value = data.get("value")
    if not key:
        return jsonify({"success": False, "message": "缺少设置键名"})
    success, message = _service.update_setting(key, value)
    if success:
        add_activity(
            username=session.get("username"),
            description=f"更新设置: {key}={value}",
            ip=_service.get_real_ip(request),
            path=request.path,
            user_agent=request.user_agent.string,
            is_logged_in=True,
        )
    return jsonify({"success": success, "message": message})
