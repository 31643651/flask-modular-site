"""
画廊偏好设置路由
"""

from flask import Blueprint, request, jsonify, session
from Module.core.gallery_service import GalleryService
from Module.gallery.guards import check_gallery_enabled

gallery_preferences_bp = Blueprint(
    "gallery_preferences", __name__, url_prefix="/gallery", template_folder="templates"
)
_service = GalleryService()


# 功能开关守卫（ADR-0009：三蓝图共用 guards.check_gallery_enabled）
gallery_preferences_bp.before_request(check_gallery_enabled)


@gallery_preferences_bp.route("/api/preferences")
def get_preferences():
    username = session.get("username")
    if not username:
        prefs = _service.load_preferences()
        return jsonify(
            {"success": True, "preferences": prefs.get("default_preferences", {})}
        )
    prefs = _service.get_user_preferences(username)
    return jsonify({"success": True, "preferences": prefs})


@gallery_preferences_bp.route("/api/preferences", methods=["POST"])
def save_preferences():
    username = session.get("username")
    if not username:
        return jsonify({"success": False, "message": "未登录"}), 401
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "message": "无效数据"})
    # 前端发送 { "preferences": {...} } 包裹形态；兼容裸字典旧形态
    prefs = data.get("preferences") if isinstance(data, dict) else None
    _service.save_user_preferences(username, prefs if isinstance(prefs, dict) else data)
    return jsonify({"success": True, "message": "偏好已保存"})


@gallery_preferences_bp.route("/api/preferences/default")
def get_default_preferences():
    prefs = _service.load_preferences()
    return jsonify(
        {"success": True, "preferences": prefs.get("default_preferences", {})}
    )
