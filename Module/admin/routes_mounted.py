"""
管理后台挂载页面路由
"""

from flask import Blueprint, session, request, jsonify
from Module.core.admin_service import AdminService
from Module.common.user_utils import require_superadmin, add_activity

admin_mounted_bp = Blueprint("admin_mounted", __name__, url_prefix="/admin", template_folder="templates")
_service = AdminService()


@admin_mounted_bp.route("/mounted-pages", methods=["GET"])
def get_mounted_pages():
    check = require_superadmin()
    if check:
        return check
    pages = _service.get_mounted_pages()
    return jsonify({"success": True, "pages": pages})


@admin_mounted_bp.route("/mounted-pages", methods=["POST"])
def add_mounted_page():
    check = require_superadmin()
    if check:
        return check
    data = request.get_json()
    name = data.get("name", "").strip()
    path = data.get("path", "").strip()
    page_type = data.get("type", "file")
    if not name or not path:
        return jsonify({"success": False, "message": "名称和路径不能为空"})
    success, message = _service.add_mounted_page(name, path, page_type)
    if success:
        add_activity(
            username=session.get("username"), description=f"添加挂载页面：{name}",
            ip=_service.get_real_ip(request), path=request.path,
            user_agent=request.user_agent.string, is_logged_in=True,
        )
        return jsonify({
            "success": True,
            "message": message,
            "name": name,
            "page_type": page_type,
            "redirect_url": "/" + name,
        })
    return jsonify({"success": success, "message": message})


@admin_mounted_bp.route("/mounted-pages/<name>", methods=["DELETE"])
def remove_mounted_page(name):
    check = require_superadmin()
    if check:
        return check
    success, message = _service.remove_mounted_page(name)
    if success:
        add_activity(
            username=session.get("username"), description=f"删除挂载页面：{name}",
            ip=_service.get_real_ip(request), path=request.path,
            user_agent=request.user_agent.string, is_logged_in=True,
        )
    return jsonify({"success": success, "message": message})
