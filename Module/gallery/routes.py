"""
画廊主路由
"""

import random
import time
from pathlib import Path
from flask import (
    Blueprint,
    abort,
    render_template,
    send_file,
    request,
    jsonify,
    session,
)
from Module.core.gallery_service import GalleryService, sanitize_path, _resolve_subdir
from Module.common.security import generate_csrf_token
from Module.gallery.guards import check_gallery_enabled

gallery_bp = Blueprint(
    "gallery", __name__, url_prefix="/gallery", template_folder="templates"
)
_service = GalleryService()


# 功能开关守卫（ADR-0009：三蓝图共用 guards.check_gallery_enabled）
gallery_bp.before_request(check_gallery_enabled)


def get_relative_path(full_path):
    """获取相对路径"""
    root = _service.get_gallery_root()
    if root is None:
        return Path(full_path)
    try:
        return Path(full_path).resolve().relative_to(root.resolve())
    except ValueError:
        return Path(full_path)


def _build_gallery_data(folder, root):
    """构建画廊模板数据"""
    subfolders = []
    images = []
    scan = _service.get_folder_scan(folder)
    if scan:
        image_list, subfolder_list = scan
        images = ["/gallery/image/" + str(get_relative_path(img)) for img in image_list]
        for sub in subfolder_list:
            sub_rel = get_relative_path(sub)
            sub_count = _service.count_images_in_folder(sub)
            first_img = _service.get_first_image(sub)
            cover = (
                "/gallery/image/" + str(get_relative_path(first_img))
                if first_img
                else None
            )
            subfolders.append(
                {
                    "path": str(sub_rel),
                    "name": sub.name,
                    "count": sub_count,
                    "cover": cover,
                }
            )
    folder_name = folder.name if folder != root else "图片画廊"

    # relative_path
    relative_path = "" if folder == root else str(get_relative_path(folder))

    # has_favorites / favorites_count
    has_favorites = False
    favorites_count = 0
    from flask import session as flask_session

    username = flask_session.get("username")
    if username:
        all_favs = _service.load_favorites()
        user_favs = all_favs.get(username, [])
        favorites_count = len(user_favs)
        has_favorites = favorites_count > 0

    # breadcrumb
    breadcrumb = []
    if folder != root:
        parts = list(Path(relative_path).parts) if relative_path else []
        for i, part in enumerate(parts):
            path_str = "/".join(parts[: i + 1])
            breadcrumb.append({"name": part, "path": path_str})

    return (
        subfolders,
        images,
        folder_name,
        relative_path,
        has_favorites,
        favorites_count,
        breadcrumb,
    )


@gallery_bp.route("")
@gallery_bp.route("/")
def index():
    """画廊首页"""
    root = _service.get_gallery_root()
    path_empty = root is None
    if path_empty:
        return render_template("gallery/index.html", path_empty=True, csrf_token=generate_csrf_token())
    (
        subfolders,
        images,
        folder_name,
        relative_path,
        has_favorites,
        favorites_count,
        breadcrumb,
    ) = _build_gallery_data(root, root)
    return render_template(
        "gallery/index.html",
        path_empty=False,
        subfolders=subfolders,
        images=images,
        folder_name=folder_name,
        relative_path=relative_path,
        has_favorites=has_favorites,
        favorites_count=favorites_count,
        breadcrumb=breadcrumb,
        user_preferences=_service.get_user_preferences(username=session.get("username")),
        device_specific={},
        csrf_token=generate_csrf_token(),
    )


@gallery_bp.route("/<path:subpath>")
def browse(subpath):
    """浏览画廊子目录"""
    root = _service.get_gallery_root()
    if root is None:
        return render_template("gallery/index.html", path_empty=True, csrf_token=generate_csrf_token())
    folder = _resolve_subdir(subpath, root)
    if folder is None:
        abort(404)
    if not folder.is_dir():
        return render_template("gallery/index.html", path_empty=True, csrf_token=generate_csrf_token())
    (
        subfolders,
        images,
        folder_name,
        relative_path,
        has_favorites,
        favorites_count,
        breadcrumb,
    ) = _build_gallery_data(folder, root)
    return render_template(
        "gallery/index.html",
        path_empty=False,
        subfolders=subfolders,
        images=images,
        folder_name=folder_name,
        relative_path=relative_path,
        has_favorites=has_favorites,
        favorites_count=favorites_count,
        breadcrumb=breadcrumb,
        user_preferences=_service.get_user_preferences(username=session.get("username")),
        device_specific={},
        csrf_token=generate_csrf_token(),
    )


# ADR-0012：发现区结果缓存与限量（控制首屏资源总量）
_RANDOM_CACHE_TTL = 300  # 秒
_RANDOM_FOLDER_LIMIT = 8  # 最多取 8 个文件夹 × 4 张 + 根目录 4 张
_random_cache = {"key": None, "expires": 0.0, "images": []}


@gallery_bp.route("/api/random-images")
def random_images():
    """
    获取随机图片（发现功能）

    原始设计：从每个子文件夹中随机选择4张图片，确保发现页面的图片来自不同文件夹，
    提供更加多样化的浏览体验。
    ADR-0012：结果缓存 300 秒 + 最多 8 个文件夹（≤36 张），避免全树高频扫描与
    一次性渲染数百张原图。
    """
    root = _service.get_gallery_root()
    if root is None:
        return jsonify({"success": False, "message": "画廊路径未配置"}), 400

    cache_key = str(root.resolve())
    now = time.time()
    if _random_cache["key"] == cache_key and _random_cache["expires"] > now:
        return jsonify({"success": True, "images": _random_cache["images"]})

    # 获取所有子文件夹
    all_subfolders = _service.get_all_subfolders_recursive(root)

    folder_random_images = []
    for folder in all_subfolders:
        folder_images = _service.get_all_images(folder)
        if folder_images and len(folder_images) >= 4:
            # 从每个有4张以上图片的文件夹中随机选择4张
            selected = random.sample(folder_images, 4)
            folder_random_images.append((folder.name, selected))

    # 根目录也参与
    root_images = _service.get_all_images(root)
    if root_images and len(root_images) >= 4:
        selected = random.sample(root_images, 4)
        folder_random_images.append(('root', selected))

    # 随机打乱文件夹顺序，并限量取前 N 个文件夹（ADR-0012）
    random.shuffle(folder_random_images)
    folder_random_images = folder_random_images[:_RANDOM_FOLDER_LIMIT]

    # 收集所有图片
    all_images = []
    for folder_name, images in folder_random_images:
        all_images.extend(images)

    image_urls = ["/gallery/image/" + str(get_relative_path(img)) for img in all_images]
    _random_cache["key"] = cache_key
    _random_cache["expires"] = now + _RANDOM_CACHE_TTL
    _random_cache["images"] = image_urls
    return jsonify({"success": True, "images": image_urls})


@gallery_bp.route("/api/folder-images/<path:subpath>")
def folder_images(subpath):
    root = _service.get_gallery_root()
    if root is None:
        return jsonify({"success": False, "message": "画廊路径未配置"}), 400
    folder = _resolve_subdir(subpath, root)
    if folder is None or not folder.is_dir():
        return jsonify({"success": False, "message": "文件夹不存在"}), 404
    images = _service.get_all_images_recursive(folder)
    result = ["/gallery/image/" + str(get_relative_path(img)) for img in images]
    return jsonify({"success": True, "images": result})


@gallery_bp.route("/api/search")
def search():
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"success": True, "results": {"folders": [], "images": []}})
    root = _service.get_gallery_root()
    if root is None:
        return jsonify({"success": False, "message": "画廊路径未配置"}), 400
    
    # 搜索匹配的文件夹
    matched_folders = []
    for item in root.rglob("*"):
        if item.is_dir() and query.lower() in item.name.lower():
            rel_path = get_relative_path(item)
            first_img = _service.get_first_image(item)
            matched_folders.append({
                "path": str(rel_path),
                "name": item.name,
                "count": _service.count_images_in_folder(item),
                "cover": (
                    "/gallery/image/" + str(get_relative_path(first_img))
                    if first_img
                    else None
                ),
            })
    
    # 搜索匹配的图片
    all_images = _service.get_all_images_recursive(root)
    matched_images = []
    for img in all_images:
        if query.lower() in img.name.lower():
            matched_images.append({
                "url": "/gallery/image/" + str(get_relative_path(img)),
                "name": img.name
            })
    
    return jsonify({
        "success": True, 
        "results": {
            "folders": matched_folders,
            "images": matched_images
        }
    })


@gallery_bp.route("/image/<path:image_path>")
def serve_image(image_path):
    image_path = sanitize_path(image_path)
    root = _service.get_gallery_root()
    if root is None:
        return jsonify({"success": False, "message": "画廊路径未配置"}), 404
    full_path = (root / image_path).resolve()
    try:
        full_path.relative_to(root.resolve())
    except ValueError:
        return jsonify({"success": False, "message": "路径不合法"}), 403
    if not full_path.is_file():
        return jsonify({"success": False, "message": "文件不存在"}), 404
    return send_file(full_path)


@gallery_bp.route("/favorites")
def favorites_page():
    from flask import session as flask_session
    from pathlib import Path
    username = flask_session.get("username")
    favorites = []
    if username:
        all_favs = _service.load_favorites()
        user_favs = all_favs.get(username, [])
        root = _service.get_gallery_root()
        if root:
            for fav_path in user_favs:
                # 尝试作为相对路径或绝对路径处理
                fav_file = Path(fav_path)
                if not fav_file.is_absolute():
                    fav_file = root / fav_path
                if fav_file.is_file():
                    try:
                        rel_path = str(fav_file.resolve().relative_to(root.resolve()))
                    except ValueError:
                        rel_path = fav_path
                    url = "/gallery/image/" + rel_path
                    name = fav_file.name
                    favorites.append({"url": url, "path": rel_path, "name": name})
    return render_template(
        "gallery/favorites.html",
        favorites=favorites,
        total=len(favorites),
        csrf_token=generate_csrf_token(),
    )
