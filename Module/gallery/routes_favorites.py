"""
画廊收藏路由
"""

from flask import Blueprint, request, jsonify, session
from Module.core.gallery_service import GalleryService
from Module.gallery.guards import check_gallery_enabled

gallery_favorites_bp = Blueprint(
    "gallery_favorites", __name__, url_prefix="/gallery", template_folder="templates"
)
_service = GalleryService()


# 功能开关守卫（ADR-0009：三蓝图共用 guards.check_gallery_enabled）
gallery_favorites_bp.before_request(check_gallery_enabled)


def _get_username():
    return session.get("username")


def _normalize_path(path):
    return path.replace("\\", "/")


@gallery_favorites_bp.route("/api/favorites")
def get_favorites():
    username = _get_username()
    if not username:
        return jsonify({"success": False, "message": "未登录"}), 401
    favorites = _service.load_favorites()
    user_favs = favorites.get(username, [])
    return jsonify({"success": True, "favorites": user_favs})


@gallery_favorites_bp.route("/api/favorite/add", methods=["POST"])
def add_favorite():
    username = _get_username()
    if not username:
        return jsonify({"success": False, "message": "未登录"}), 401
    data = request.get_json()
    path = data.get("path", "").strip()
    if not path:
        return jsonify({"success": False, "message": "路径不能为空"}), 400

    path = _normalize_path(path)

    favorites = _service.load_favorites()
    if username in favorites and path in favorites[username]:
        return jsonify({"success": True, "message": "已收藏"})

    from datetime import datetime

    with _service.db.transaction():
        _service.db.execute(
            "INSERT INTO favorites (username, path, added_at) VALUES (?, ?, ?)",
            (username, path, datetime.now().isoformat()),
        )
    return jsonify({"success": True, "message": "已添加收藏"})


@gallery_favorites_bp.route("/api/favorite/remove", methods=["POST"])
def remove_favorite():
    username = _get_username()
    if not username:
        return jsonify({"success": False, "message": "未登录"}), 401
    data = request.get_json()
    path = data.get("path", "").strip()
    if not path:
        return jsonify({"success": False, "message": "路径不能为空"}), 400

    path = _normalize_path(path)

    with _service.db.transaction():
        _service.db.execute(
            "DELETE FROM favorites WHERE username = ? AND path = ?",
            (username, path),
        )
    return jsonify({"success": True, "message": "已取消收藏"})


@gallery_favorites_bp.route("/api/favorite/check", methods=["POST"])
def check_favorite():
    username = _get_username()
    if not username:
        return jsonify({"success": False, "message": "未登录"}), 401
    data = request.get_json()
    path = data.get("path", "").strip()

    path = _normalize_path(path)

    favorites = _service.load_favorites()
    user_favs = favorites.get(username, [])
    is_fav = path in user_favs
    return jsonify({"success": True, "is_favorite": is_fav})
