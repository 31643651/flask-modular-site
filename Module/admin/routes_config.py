"""
管理后台配置管理路由
"""

from flask import Blueprint, render_template, session, request, jsonify
from Module.core.admin_service import AdminService
from Module.common.user_utils import require_superadmin, add_activity
from Module.common.security import generate_csrf_token

admin_config_bp = Blueprint(
    "admin_config", __name__, url_prefix="/admin", template_folder="templates"
)
_service = AdminService()


@admin_config_bp.route("/config")
def config_page():
    check = require_superadmin()
    if check:
        return check
    server_info = _service.load_server_info()
    csrf_token = generate_csrf_token()
    return render_template(
        "admin/config.html", server_info=server_info, csrf_token=csrf_token
    )


@admin_config_bp.route("/config/api")
def config_api():
    """获取配置数据（含设置状态）"""
    check = require_superadmin()
    if check:
        return check
    config = _service.get_config()
    settings = _service.get_settings()
    config["settings"] = settings
    return jsonify({"success": True, "config": config})


@admin_config_bp.route("/config/update", methods=["POST"])
def update_config():
    check = require_superadmin()
    if check:
        return check
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "message": "无效的请求数据"})
    success, message = _service.update_config(data)
    if success:
        add_activity(
            username=session.get("username"),
            description="更新系统配置",
            ip=_service.get_real_ip(request),
            path=request.path,
            user_agent=request.user_agent.string,
            is_logged_in=True,
        )
    return jsonify({"success": success, "message": message})
