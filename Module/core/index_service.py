"""
首页 / 挂载页业务逻辑服务

从 Module.index.index 抽取的纯逻辑（无 Flask 依赖）：
- 壁纸：URL 选取（首屏优先最小文件）、路径沙箱解析、按文件名寻址、MIME
- 挂载：静态文件 MIME 覆盖、站根绝对引用改写、目录条目与面包屑构建

路由层只保留 abort/redirect/响应编排，业务规则集中于此，便于单测与复用。
"""

import mimetypes
import re
from pathlib import Path

WALLPAPER_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp")

# 系统敏感路径（禁止壁纸使用）
SENSITIVE_SYSTEM_PATHS = [
    "C:\\Windows",
    "C:\\Program Files",
    "C:\\Program Files (x86)",
    "C:\\Users",
    "/etc",
    "/proc",
    "/sys",
    "/bin",
    "/sbin",
    "/root",
]

# 挂载静态文件的显式 MIME 映射（优先于 mimetypes 猜测；<script type="module"> 有严格 MIME 检查）
MOUNTED_MIME_OVERRIDES = {
    ".js": "text/javascript", ".mjs": "text/javascript",
    ".css": "text/css", ".svg": "image/svg+xml", ".wasm": "application/wasm",
    ".woff": "font/woff", ".woff2": "font/woff2",
    ".json": "application/json", ".webmanifest": "application/manifest+json",
    ".xml": "application/xml", ".txt": "text/plain",
    ".html": "text/html", ".htm": "text/html",
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".webp": "image/webp", ".ico": "image/x-icon",
}

# 挂载 HTML 中站根绝对引用的保守匹配：仅双引号形态 src="/..."/href="/..."，
# 值以单个 / 开头；// 协议相对、外链、data:、# 锚点、相对路径不进值捕获或被排除
_HTML_ABS_ATTR_RE = re.compile(r'((?:src|href)\s*=\s*")(/[^"]*)(")')

# 目录浏览时跳过的条目
_HIDDEN_DIR_NAMES = ("__pycache__", ".git", ".svn", ".env", "node_modules")


def get_wallpaper_mime(ext):
    """壁纸扩展名 → MIME"""
    return {
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
    }.get(ext, "image/jpeg")


def pick_smallest_wallpaper_url(wallpaper_config, app_root):
    """
    首屏壁纸 URL（随机性让位于稳定性：取体积最小的文件，保证背景快速出现）。

    Returns:
        str: "/static/wallpaper?img=<name>" 或 ""
    """
    if not (wallpaper_config.get("enabled") and wallpaper_config.get("path")):
        return ""
    try:
        raw = Path(wallpaper_config["path"])
        base = raw if raw.is_absolute() else (Path(app_root) / raw)
        base = base.resolve()
        if base.is_dir():
            files = []
            for ext in WALLPAPER_IMAGE_EXTENSIONS:
                files.extend(sorted(base.glob(f"*{ext}")))
            if not files:
                return ""
            from urllib.parse import quote

            chosen = min(files, key=lambda p: p.stat().st_size)
            return "/static/wallpaper?img=" + quote(chosen.name)
        return "/static/wallpaper"
    except Exception:
        return ""


def resolve_wallpaper_path(wallpaper_config, app_root):
    """
    解析壁纸绝对路径并做沙箱校验。

    Returns:
        tuple: (Path | None, error_status | None)
               - 正常：返回 (path, None)
               - 未启用：返回 (None, None)
               - 越权/敏感目录：返回 (None, 403)
               - 不存在：返回 (None, 404)
    """
    if not (wallpaper_config.get("enabled") and wallpaper_config.get("path")):
        return (None, None)
    app_root = Path(app_root)
    wallpaper_path = app_root / wallpaper_config["path"]

    try:
        resolved = wallpaper_path.resolve()
        resolved.relative_to(app_root.resolve())
    except ValueError:
        return (None, 403)

    for sensitive in SENSITIVE_SYSTEM_PATHS:
        try:
            resolved.relative_to(Path(sensitive).resolve())
            return (None, 403)
        except ValueError:
            continue

    if not wallpaper_path.exists():
        return (None, 404)

    return (wallpaper_path, None)


def resolve_named_wallpaper(wallpaper_path, img_name):
    """按文件名在壁纸目录内解析（拒绝分隔符/..，必须仍是目录内的普通文件）"""
    if not img_name:
        return None
    if "/" in img_name or "\\" in img_name or ".." in img_name:
        return None
    if not wallpaper_path.is_dir():
        return None
    candidate = (wallpaper_path / img_name).resolve()
    try:
        candidate.relative_to(wallpaper_path.resolve())
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    return candidate


def pick_random_wallpaper_file(wallpaper_path):
    """目录壁纸随机取一张；非目录或空目录返回 None"""
    if not wallpaper_path.is_dir():
        return None
    image_files = []
    for ext in WALLPAPER_IMAGE_EXTENSIONS:
        image_files.extend(wallpaper_path.glob(f"*{ext}"))
    if not image_files:
        return None
    import random

    return random.choice(image_files)


def get_mounted_mime(file_path):
    """挂载文件 MIME（显式映射优先，其次 mimetypes，兜底 octet-stream）"""
    mimetype, _ = mimetypes.guess_type(str(file_path))
    override = MOUNTED_MIME_OVERRIDES.get(Path(file_path).suffix.lower())
    if override:
        mimetype = override
    return mimetype or "application/octet-stream"


def rewrite_mounted_html(html_text, page_name):
    """把挂载 HTML 中站根绝对路径的资源引用改写为挂载前缀路径（保守规则）"""

    def _sub(match):
        value = match.group(2)
        if value.startswith("//") or value == "/":
            return match.group(0)
        return f"{match.group(1)}/{page_name}{value}{match.group(3)}"

    return _HTML_ABS_ATTR_RE.sub(_sub, html_text)


def build_directory_items(directory_path, current_path):
    """目录条目列表（跳过隐藏/敏感项，并做 resolve 后仍在目录内的双重校验）"""
    directory_path = Path(directory_path)
    try:
        resolved_dir = directory_path.resolve()
    except (ValueError, OSError):
        return []

    items = []
    for item in sorted(directory_path.iterdir()):
        if item.name.startswith("."):
            continue
        if item.name in _HIDDEN_DIR_NAMES:
            continue
        try:
            resolved_item = item.resolve()
            resolved_item.relative_to(resolved_dir)
        except (ValueError, OSError):
            continue

        is_file = item.is_file()
        items.append(
            {
                "name": item.name,
                "is_file": is_file,
                "size": item.stat().st_size if is_file else None,
                "modified": item.stat().st_mtime,
                "relative_path": (
                    f"{current_path}/{item.name}" if current_path else item.name
                ),
            }
        )
    return items


def build_breadcrumb(page_name, current_path):
    """目录浏览面包屑（首项为挂载页名）"""
    breadcrumb = [{"name": page_name, "path": ""}]
    if current_path:
        path_so_far = ""
        for part in current_path.split("/"):
            path_so_far = f"{path_so_far}/{part}" if path_so_far else part
            breadcrumb.append({"name": part, "path": path_so_far})
    return breadcrumb
