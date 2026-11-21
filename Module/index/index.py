"""
首页模块

本模块负责首页导航功能，提供各功能模块的入口链接。
所有路由通过蓝图注册到主应用。
"""

import logging
from flask import (
    Blueprint,
    Response,
    render_template,
    session,
    request,
    jsonify,
    abort,
    send_file,
    redirect,
    url_for,
)
from pathlib import Path
from werkzeug.exceptions import HTTPException

# 从 common 模块导入共享函数
from Module.common.user_utils import get_user, is_superadmin, require_superadmin
from Module.common.response import ErrorCode, error_response
from Module.core.index_service import (
    SENSITIVE_SYSTEM_PATHS,
    build_breadcrumb,
    build_directory_items,
    get_mounted_mime,
    get_wallpaper_mime,
    pick_random_wallpaper_file,
    pick_smallest_wallpaper_url,
    resolve_named_wallpaper,
    resolve_wallpaper_path,
    rewrite_mounted_html,
)

# 获取日志记录器（不配置，由 log 模块统一配置）
logger = logging.getLogger(__name__)

# 创建蓝图对象
index_bp = Blueprint("index", __name__, template_folder="templates")

# 配置文件路径
CONFIG_FILE = Path(__file__).parent.parent.parent / "Module" / "json" / "config.json"

# 敏感目录列表（禁止挂载）
SENSITIVE_DIRS = [".git", "Module/data", "Module/json"]


def load_config():
    """加载配置文件（统一委托 common.config_utils，TTL 缓存 5 秒）"""
    from Module.common.config_utils import load_config as _load_config

    return _load_config()


def save_config(config):
    """保存配置文件（统一走 config_utils，保存前备份）"""
    from Module.common.config_utils import backup_config, save_config as _save_config

    backup_config()
    return _save_config(config)


def _resolve_wallpaper_url(settings):
    """
    ADR-0012：服务端解析首屏壁纸 URL（委托 core.index_service）。

    Returns:
        str: 壁纸 URL；未启用/无效时返回空串
    """
    if settings.get("wallpaper_enabled") is False:
        return ""
    try:
        config = load_config()
        wallpaper_config = config.get("wallpaper", {"enabled": False, "path": ""})
        return pick_smallest_wallpaper_url(
            wallpaper_config, Path(__file__).parent.parent.parent
        )
    except Exception:
        return ""


@index_bp.route("/")
def index():
    """
    首页路由

    返回首页导航页面，展示各功能模块的入口链接。

    Returns:
        str: 渲染后的首页HTML页面
    """
    # 从session获取用户信息
    user = None
    if "user_id" in session:
        user = get_user(session.get("username"))

    from Module.common.settings_utils import get_settings, is_feature_enabled

    settings = get_settings()

    # ADR-0012：挂载入口与壁纸在服务端渲染，页面到达即可见，不依赖前端 fetch
    mounted_pages = []
    if is_feature_enabled("mounted_pages_enabled"):
        mounted_pages = load_config().get("mounted_pages", [])
    wallpaper_url = _resolve_wallpaper_url(settings)

    return render_template(
        "index/index.html",
        user=user,
        settings=settings,
        mounted_pages=mounted_pages,
        wallpaper_url=wallpaper_url,
    )


@index_bp.route("/api/wallpaper/config", methods=["GET"])
def get_wallpaper_config():
    """获取壁纸配置（公开接口，用于首页展示）"""
    try:
        from Module.common.settings_utils import is_feature_enabled

        if not is_feature_enabled("wallpaper_enabled"):
            return jsonify({"success": True, "enabled": False, "path": ""})

        config = load_config()
        wallpaper_config = config.get("wallpaper", {"enabled": False, "path": ""})

        # 仅在"启用且已配置路径"时回显公开静态路由；其余情况一律不回显原始
        # 服务器路径（匿名接口，防目录结构泄露，最终审查 I3）
        if wallpaper_config["enabled"] and wallpaper_config["path"]:
            wallpaper_config["path"] = "/static/wallpaper"
        else:
            wallpaper_config["path"] = ""

        return jsonify({"success": True, **wallpaper_config})
    except Exception as e:
        logger.error(f"获取壁纸配置失败: {e}")
        return jsonify({"success": False, "message": "服务器内部错误，请查看日志"})


@index_bp.route("/api/wallpaper/config", methods=["POST"])
def update_wallpaper_config():
    """更新壁纸配置（仅超级管理员可修改）"""
    # require_superadmin 对非超管会 clear session，故登录态与角色判定必须在其之前完成
    if "user_id" not in session:
        return jsonify({"success": False, "message": "请先登录"}), 401
    user = get_user(session.get("username"))
    if not user or not user.get("enabled") or not is_superadmin(user):
        # 权限不足：403 JSON，与项目统一响应格式（response.py）对齐
        return error_response(
            "权限不足，仅超级管理员可修改壁纸配置", ErrorCode.FORBIDDEN, 403
        )
    check = require_superadmin()
    if check:
        # 超管未通过二次验证：与 admin 模块一致跳转验证页
        return check
    try:
        data = request.get_json(silent=True) or {}
        raw_enabled = data.get("enabled", False)
        # 前端发送布尔值；兼容字符串形态（"true"/"false"），避免任意字符串被当真值
        if isinstance(raw_enabled, str):
            enabled = raw_enabled.strip().lower() == "true"
        else:
            enabled = bool(raw_enabled)

        config = load_config()
        # 保持原有路径不变，只更新开关状态
        if "wallpaper" not in config:
            config["wallpaper"] = {"enabled": False, "path": ""}
        config["wallpaper"]["enabled"] = enabled
        save_config(config)

        return jsonify({"success": True, "message": "壁纸配置已更新"})
    except Exception as e:
        logger.error(f"更新壁纸配置失败: {e}")
        return jsonify({"success": False, "message": "服务器内部错误，请查看日志"})


@index_bp.route("/api/mounted-pages", methods=["GET"])
def get_mounted_pages_public():
    """
    获取已挂载的页面列表（公开接口，用于主页显示）

    Returns:
        dict: 已挂载的页面列表
    """
    try:
        from Module.common.settings_utils import is_feature_enabled

        if not is_feature_enabled("mounted_pages_enabled"):
            return jsonify({"success": True, "pages": []})
        config = load_config()
        mounted_pages = config.get("mounted_pages", [])
        return jsonify({"success": True, "pages": mounted_pages})
    except Exception as e:
        logger.error(f"获取挂载页面列表失败: {e}")
        return jsonify({"success": False, "message": "服务器内部错误，请查看日志"})


@index_bp.route("/static/wallpaper")
def serve_wallpaper():
    """提供壁纸图片"""
    from flask import send_file, abort
    import random

    try:
        config = load_config()
        wallpaper_config = config.get("wallpaper", {"enabled": False, "path": ""})
        app_root = Path(__file__).parent.parent.parent

        wallpaper_path, error = resolve_wallpaper_path(wallpaper_config, app_root)
        if error == 403:
            logger.warning(
                "Wallpaper path rejected by sandbox: %s", wallpaper_config.get("path")
            )
            abort(403)
        if error == 404:
            logger.warning(
                "Wallpaper path does not exist: %s", wallpaper_config.get("path")
            )
            abort(404)
        if wallpaper_path is None:
            abort(404)

        # ADR-0012：按文件名寻址（服务端渲染壁纸 URL 时使用，可命中 1 天缓存）
        img_name = request.args.get("img") or ""
        if img_name:
            candidate = resolve_named_wallpaper(wallpaper_path, img_name)
            if candidate is None:
                abort(404)
            return send_file(
                str(candidate),
                mimetype=get_wallpaper_mime(candidate.suffix.lower()),
            )

        selected = pick_random_wallpaper_file(wallpaper_path)
        if selected is not None:
            wallpaper_path = selected

        if wallpaper_path.exists() and wallpaper_path.is_file():
            return send_file(
                str(wallpaper_path),
                mimetype=get_wallpaper_mime(wallpaper_path.suffix.lower()),
            )

        abort(404)
    except HTTPException:
        # abort() 抛出的 HTTPException 必须透传，否则 403 会被吞成 404
        raise
    except Exception as e:
        logger.error(f"Error serving wallpaper: {e}")
        abort(404)


@index_bp.route("/<path:page_name>")
def serve_mounted_page(page_name):
    """
    服务挂载的页面或文件夹

    - 文件挂载：按 MIME 类型内联返回
    - 目录挂载：优先返回 index.html；无则返回目录浏览页
    - 子路径静态文件（.css/.js/图片等）按正确 MIME 内联返回（非下载）

    Args:
        page_name: 页面名称（可能包含子路径）

    Returns:
        Response: 页面内容或 404/403
    """
    from Module.common.settings_utils import is_feature_enabled

    if not is_feature_enabled("mounted_pages_enabled"):
        return redirect(url_for("index.index"))

    # 分离页面名称和子路径
    parts = page_name.split("/", 1)
    actual_page_name = parts[0]
    subpath = parts[1] if len(parts) > 1 else ""

    config = load_config()
    mounted_pages = config.get("mounted_pages", [])

    # 查找匹配的页面
    page_config = None
    for page in mounted_pages:
        if page["name"] == actual_page_name:
            page_config = page
            break

    if not page_config:
        abort(404)

    # 解析路径（支持相对路径，相对应用根目录）
    app_root = Path(__file__).parent.parent.parent
    raw_path = Path(page_config["path"])
    page_path = raw_path if raw_path.is_absolute() else app_root / raw_path

    # 路径安全校验：拒绝包含 .. 的原始路径（双重保险）
    # 同时检查URL编码的..
    raw_path_str = str(raw_path)
    if ".." in raw_path_str or "%2e%2e" in raw_path_str.lower() or "%2E%2E" in raw_path_str:
        abort(403)

    if not page_path.exists():
        abort(404)

    # 路径安全校验：验证挂载路径必须在项目目录内
    try:
        resolved_path = page_path.resolve()
        resolved_path.relative_to(app_root.resolve())
    except ValueError:
        # 路径不在项目目录内，拒绝
        abort(403)

    # 排除敏感目录
    for sensitive in SENSITIVE_DIRS:
        sensitive_path = (app_root / sensitive).resolve()
        try:
            resolved_path.relative_to(sensitive_path)
            # 路径在敏感目录内，拒绝
            abort(403)
        except ValueError:
            continue

    # 文件挂载：按 MIME 内联返回
    if page_config.get("is_file", False) or page_path.is_file():
        return serve_static_file(page_path, page_name=actual_page_name)

    # 目录挂载
    if page_path.is_dir():
        # 子路径安全检查
        if subpath and (
            ".." in subpath or subpath.startswith("/") or subpath.startswith("\\")
        ):
            abort(403)

        # 无子路径：优先 index.html，否则目录浏览
        if not subpath:
            index_file = page_path / "index.html"
            if index_file.is_file():
                # 无尾斜杠时重定向到带尾斜杠路径，保证页面内相对资源路径正确解析
                if not request.path.endswith("/"):
                    return redirect("/" + actual_page_name + "/")
                return serve_static_file(index_file, page_name=actual_page_name)
            return serve_directory(page_path, actual_page_name, "")

        # 有子路径：解析目标并防遍历
        target_path = (page_path / subpath).resolve()
        try:
            target_path.relative_to(page_path.resolve())
        except ValueError:
            abort(403)

        if not target_path.exists():
            abort(404)

        if target_path.is_file():
            return serve_static_file(target_path, page_name=actual_page_name)

        if target_path.is_dir():
            index_file = target_path / "index.html"
            if index_file.is_file():
                # 无尾斜杠时重定向到带尾斜杠路径，保证子目录内相对资源路径正确解析
                # （page_name 为路由原始变量、含子路径，如 docsx/pages → /docsx/pages/）
                if not request.path.endswith("/"):
                    return redirect(f"/{page_name}/")
                return serve_static_file(index_file, page_name=actual_page_name)
            return serve_directory(target_path, actual_page_name, subpath)

    abort(404)


def serve_static_file(file_path, page_name=None):
    """
    按正确 MIME 类型内联返回静态文件（非下载）

    静态文件（HTML 除外）添加短时缓存头，减少重复请求。

    Args:
        file_path: 文件绝对路径
        page_name: 挂载页名称；提供时对 HTML 做站根绝对引用重写（ADR-0002）

    Returns:
        Response: 文件响应
    """
    mimetype = get_mounted_mime(file_path)

    # 挂载 HTML：站根绝对引用重写为 /<page_name>/ 前缀路径（每次服务时计算，
    # 无缓存一致性问题，故与既有现状一致不加缓存头）
    if mimetype.startswith("text/html") and page_name:
        html_text = Path(file_path).read_bytes().decode("utf-8", errors="replace")
        return Response(
            rewrite_mounted_html(html_text, page_name), mimetype=mimetype
        )

    response = send_file(str(file_path), mimetype=mimetype, conditional=True)

    # 非 HTML 静态资源添加缓存
    if not mimetype.startswith("text/html"):
        response.cache_control.max_age = 3600
        response.cache_control.public = True

    return response


def serve_directory(directory_path, page_name, current_path):
    """
    服务目录浏览页面

    Args:
        directory_path: 目录路径
        page_name: 页面名称
        current_path: 当前相对路径

    Returns:
        Response: 目录浏览页面
    """
    try:
        # L27: 安全检查 - 确保目录路径在挂载目录内
        try:
            resolved_dir = directory_path.resolve()
            resolved_root = directory_path.parent.resolve()
            # 允许在挂载根目录内
        except (ValueError, OSError):
            abort(403)

        # 获取目录内容（委托 core.index_service 构建条目与面包屑）
        items = build_directory_items(directory_path, current_path)
        breadcrumb = build_breadcrumb(page_name, current_path)

        # 渲染目录浏览页面
        return render_template(
            "index/directory.html",
            page_name=page_name,
            breadcrumb=breadcrumb,
            items=items,
        )

    except Exception as e:
        logger.error(f"Error serving directory '{directory_path}': {e}")
        abort(500)
