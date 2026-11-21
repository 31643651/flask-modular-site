"""
管理后台封禁 IP 管理路由
"""

from flask import Blueprint, render_template, request, jsonify, session
from Module.common.user_utils import require_superadmin, add_activity
from Module.core.admin_service import AdminService
from Module.ipguard import ban_manager

admin_ip_bp = Blueprint(
    "admin_ip", __name__, url_prefix="/admin", template_folder="templates"
)
_service = AdminService()


@admin_ip_bp.before_request
def _admin_ip_auth_check():
    return require_superadmin()


@admin_ip_bp.route("/ip")
def ip_bans_page():
    check = require_superadmin()
    if check:
        return check
    bans = ban_manager.get_active_bans()
    return render_template("admin/ip.html", bans=bans)


@admin_ip_bp.route("/ip/api/bans")
def ip_bans_api():
    check = require_superadmin()
    if check:
        return check
    limit = request.args.get("limit", 20, type=int)
    bans = ban_manager.get_active_bans()
    return jsonify({"success": True, "bans": bans[:limit]})


@admin_ip_bp.route("/ip/unban", methods=["POST"])
def ip_unban():
    check = require_superadmin()
    if check:
        return check
    data = request.get_json() or {}
    ip = (data.get("ip") or "").strip()
    if not ip:
        return jsonify({"success": False, "message": "缺少 IP 参数"})
    if ban_manager.get_ban(ip) is None:
        return jsonify({"success": False, "message": "该 IP 未被封禁"})
    ban_manager.unban(ip)
    add_activity(
        username=session.get("username"),
        description=f"解除 IP 封禁：{ip}",
        ip=_service.get_real_ip(request),
        path=request.path,
        user_agent=request.user_agent.string,
        is_logged_in=True,
    )
    return jsonify({"success": True, "message": f"已解除 {ip} 的封禁"})
