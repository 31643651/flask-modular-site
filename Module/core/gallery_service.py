"""
画廊业务逻辑服务

从 gallery.py 提取的业务逻辑：图片扫描缓存、收藏管理、偏好设置。
"""

import os
import random
import threading
import time
from pathlib import Path
from datetime import datetime

from Module.common.paths import BASE_DIR, CONFIG_FILE, PREFERENCES_FILE
from Module.common.file_utils import (
    read_json_file,
    write_json_file,
    read_json_file_cached,
)
from Module.common.db_utils import query, execute, executemany, transaction


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg"}

_scan_cache = {}
_scan_cache_lock = threading.Lock()
_SCAN_CACHE_MAX = 10000
# ADR-0011：目录 mtime 校验的短 TTL（2 秒内信任缓存，跳过全树 stat）
_scan_mtime_cache = {}
_SCAN_MTIME_TTL = 2.0
# ADR-0011：子目录计数/封面结果的短 TTL 缓存
_stats_cache = {}
_STATS_TTL = 5.0

# 读-改-写互斥锁：每个存储一把（bug #27）。
# file_utils 的 _get_file_lock 为私有且非重入（持锁调用 read/write_json_file 会死锁），
# 故按简报降级方案使用模块级 threading.Lock 进程内互斥；这两个存储均为单进程使用。
_preferences_lock = threading.Lock()
_favorites_lock = threading.Lock()


def sanitize_path(path):
    """
    清理路径，移除危险字符

    Args:
        path: 原始路径字符串

    Returns:
        str: 清理后的路径
    """
    # 移除URL编码的..
    import urllib.parse
    path = urllib.parse.unquote(path)

    # 移除~和多余的/
    path = path.replace("~", "")
    while "//" in path:
        path = path.replace("//", "/")
    return path.strip("/")


def _resolve_subdir(subpath, root):
    """
    校验并解析画廊子目录路径（bug #19）

    处理顺序：
    1. sanitize_path 清理（URL 解码、去 ~、折叠 //、去首尾 /）；
    2. Windows 绝对/根化形态拒绝：C:/xxx、C:xxx 会在 pathlib 拼接时整体替换
       基准路径，/xxx、\\xxx 会保留盘符根化，均直接拒绝；
    3. 任何 .. 段直接拒绝（不静默剔除，避免改写用户请求的路径）；
    4. 拼接后 resolve 并强制 relative_to(root.resolve())，失败拒绝
       （与 serve_image 一致，同时兜底符号链接逃逸）。

    Args:
        subpath: 原始子路径（URL 路由捕获值）
        root: 已解析的画廊根目录 Path

    Returns:
        Path 或 None：合法时返回解析后的子目录，非法返回 None
    """
    subpath = sanitize_path(subpath)
    candidate = Path(subpath)
    if candidate.is_absolute() or candidate.drive or candidate.root:
        return None
    if ".." in candidate.parts:
        return None
    folder = (root / subpath).resolve()
    try:
        folder.relative_to(root.resolve())
    except ValueError:
        return None
    return folder


class GalleryService:
    """画廊服务，支持依赖注入"""

    def __init__(self, db_utils=None, file_utils=None, config_utils=None):
        self.db = db_utils or __import__(
            "Module.common.db_utils",
            fromlist=["query", "execute", "executemany", "transaction"],
        )
        self.file_utils = file_utils or __import__(
            "Module.common.file_utils", fromlist=["read_json_file", "write_json_file"]
        )
        self.config_utils = config_utils or __import__(
            "Module.common.config_utils", fromlist=["load_config"]
        )

    def load_config(self, ttl=5):
        return self.config_utils.load_config(ttl=ttl)

    def get_gallery_root(self):
        """
        获取画廊根目录路径

        Returns:
            Path or None: 画廊根目录路径，路径为空时返回 None
        """
        config = self.load_config()
        gallery_path = config.get("paths", {}).get("gallery_root_path", "")
        if (
            not gallery_path
            or not isinstance(gallery_path, str)
            or not gallery_path.strip()
        ):
            return None
        path = Path(gallery_path)
        if not path.is_absolute():
            path = BASE_DIR / path
        return path.resolve()

    def get_folder_scan(self, folder_path):
        folder = Path(folder_path)
        if not folder.is_dir():
            return None
        key = str(folder.resolve())
        now = time.time()
        with _scan_cache_lock:
            entry = _scan_cache.get(key)
            if entry is not None:
                checked_at, _ = _scan_mtime_cache.get(key, (0.0, None))
                if now - checked_at < _SCAN_MTIME_TTL:
                    # ADR-0011：2 秒内信任缓存，跳过 stat（避免全树 stat 拖慢页面）
                    return entry[1]
                try:
                    mtime = folder.stat().st_mtime
                except OSError:
                    mtime = None
                if entry[0] == mtime:
                    _scan_mtime_cache[key] = (now, mtime)
                    return entry[1]
        try:
            mtime = folder.stat().st_mtime
        except OSError:
            mtime = None
        images = []
        subfolders = []
        for item in folder.iterdir():
            if item.is_dir():
                subfolders.append(item)
            elif item.is_file() and item.suffix.lower() in IMAGE_EXTENSIONS:
                images.append(item)
        scan = (sorted(images), sorted(subfolders))
        with _scan_cache_lock:
            if len(_scan_cache) >= _SCAN_CACHE_MAX:
                _scan_cache.clear()
                _scan_mtime_cache.clear()
            _scan_cache[key] = (mtime, scan)
            _scan_mtime_cache[key] = (now, mtime)
        return scan

    def get_all_images_recursive(self, folder_path):
        scan = self.get_folder_scan(folder_path)
        if scan is None:
            return []
        images, subfolders = scan
        result = list(images)
        for sub in subfolders:
            result.extend(self.get_all_images_recursive(sub))
        return result

    def get_all_images(self, folder_path):
        """获取文件夹中所有图片（仅当前层级）"""
        scan = self.get_folder_scan(folder_path)
        if scan is None:
            return []
        images, _ = scan
        return list(images)

    def get_all_subfolders_recursive(self, folder_path):
        """递归获取所有子文件夹（包括所有深度；ADR-0012 结果缓存）"""
        cache_key = ("subdirs", str(Path(folder_path).resolve()))
        now = time.time()
        cached = _stats_cache.get(cache_key)
        if cached and cached[0] > now:
            return list(cached[1])
        scan = self.get_folder_scan(folder_path)
        if scan is None:
            result = []
        else:
            _, subfolders = scan
            result = list(subfolders)
            for sub in subfolders:
                result.extend(self.get_all_subfolders_recursive(sub))
        _stats_cache[cache_key] = (now + _STATS_TTL, list(result))
        return result

    def get_first_image(self, folder_path):
        cache_key = ("first", str(Path(folder_path).resolve()))
        now = time.time()
        cached = _stats_cache.get(cache_key)
        if cached and cached[0] > now:
            return cached[1]
        scan = self.get_folder_scan(folder_path)
        if scan is None:
            result = None
        else:
            images, subfolders = scan
            result = None
            for sub in subfolders:
                found = self.get_first_image(sub)
                if found:
                    result = found
                    break
            if result is None:
                result = images[0] if images else None
        _stats_cache[cache_key] = (now + _STATS_TTL, result)
        return result

    def get_subfolders(self, folder_path):
        scan = self.get_folder_scan(folder_path)
        return list(scan[1]) if scan else []

    def count_images_in_folder(self, folder_path):
        cache_key = ("count", str(Path(folder_path).resolve()))
        now = time.time()
        cached = _stats_cache.get(cache_key)
        if cached and cached[0] > now:
            return cached[1]
        scan = self.get_folder_scan(folder_path)
        if scan is None:
            value = 0
        else:
            images, subfolders = scan
            value = len(images) + sum(
                self.count_images_in_folder(sub) for sub in subfolders
            )
        _stats_cache[cache_key] = (now + _STATS_TTL, value)
        return value

    # --- Favorites ---
    def load_favorites(self):
        rows = self.db.query(
            "SELECT username, path, added_at FROM favorites ORDER BY id"
        )
        favorites = {}
        for r in rows:
            favorites.setdefault(r["username"], []).append(r["path"])
        return favorites

    def save_favorites(self, favorites):
        # 全量替换（DELETE+INSERT）持锁执行，避免并发下与其他写路径交错（bug #27）
        with _favorites_lock:
            with self.db.transaction():
                self.db.execute("DELETE FROM favorites")
                now = datetime.now().isoformat()
                rows = [
                    (username, path, now)
                    for username, paths in favorites.items()
                    for path in paths
                ]
                self.db.executemany(
                    "INSERT INTO favorites (username, path, added_at) VALUES (?,?,?)",
                    rows,
                )

    # --- Preferences ---
    def load_preferences(self):
        return read_json_file(
            PREFERENCES_FILE,
            default={
                "_description": "画廊用户偏好设置文件",
                "_version": "1.0",
                "default_preferences": {
                    "discover_enabled": True,
                    "discover_format": "two",
                    "discover_rounded": True,
                    "discover_shape": "square",
                    "discover_size": {"width": 150, "height": 150},
                    "sidebar_transparency": "100",
                    "lightbox_zoom_level": 1,
                    "image_quality": "high",
                    "autoplay_lightbox": False,
                },
                "device_specific": {
                    "mobile": ["discover_format", "discover_rounded"],
                    "desktop": ["discover_size", "discover_shape"],
                },
                "users": {},
            },
        )

    def get_user_preferences(self, username):
        prefs = self.load_preferences()
        users = prefs.get("users", {})
        user_prefs = users.get(username, {})
        defaults = prefs.get("default_preferences", {})
        merged = dict(defaults)
        merged.update(user_prefs)
        return merged

    def save_user_preferences(self, username, preferences):
        # 读-改-写必须整体持锁：并发保存不同用户时，无锁会导致先写者的更新被后写者
        # 基于"读取旧快照"的整文件覆盖抹掉（bug #27）
        with _preferences_lock:
            prefs = self.load_preferences()
            if "users" not in prefs:
                prefs["users"] = {}
            prefs["users"][username] = preferences
            return write_json_file(
                PREFERENCES_FILE, prefs, ensure_ascii=False, indent=2
            )
