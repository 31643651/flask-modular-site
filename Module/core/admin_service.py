"""
管理后台业务逻辑服务

从 admin.py 提取的业务逻辑，供管理后台路由调用。
支持依赖注入以便单元测试。
"""

import logging
import re
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from Module.common.paths import (
    BASE_DIR,
    SERVER_INFO_FILE,
    CONFIG_FILE,
    BACKUPS_DIR,
)
from Module.common.file_utils import read_json_file, write_json_file
from Module.common.db_utils import query, execute, executemany, transaction
from Module.common.user_utils import is_superadmin

logger = logging.getLogger(__name__)

# 系统敏感路径白名单（禁止挂载，恢复 a4713d4 H13；原写于 admin.py，
# f79b372 模块化重构拆分时丢失，ADR-0006 迁回服务层）
SENSITIVE_PATHS = [
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

# 挂载页面数量上限（历史 admin.py 口径）
MAX_MOUNTED_PAGES = 20

# update_config 顶层键白名单（恢复历史 admin.py 口径，ADR-0006）：
# mounted_pages 为 None 表示校验其数组元素结构本身，不做子键白名单
ALLOWED_CONFIG_KEYS = {
    "paths": {"book_data_path", "book_static_path", "gallery_root_path"},
    "wallpaper": {"enabled", "path"},
    "mounted_pages": None,
}


class AdminService:
    """管理后台服务，支持依赖注入"""

    def __init__(
        self, db_utils=None, file_utils=None, config_utils=None, user_utils=None
    ):
        self.db = db_utils or __import__(
            "Module.common.db_utils",
            fromlist=["query", "execute", "executemany", "transaction"],
        )
        self.file_utils = file_utils or __import__(
            "Module.common.file_utils", fromlist=["read_json_file", "write_json_file"]
        )
        self.config_utils = config_utils or __import__(
            "Module.common.config_utils", fromlist=["load_config", "save_config"]
        )
        self.user_utils = user_utils or __import__(
            "Module.common.user_utils",
            fromlist=["load_users", "save_users", "add_activity"],
        )

    # --- Server Info ---
    def init_server_info(self):
        server_info = self.file_utils.read_json_file(SERVER_INFO_FILE, default={})
        server_info["start_time"] = datetime.now().isoformat()
        if "server_name" not in server_info:
            server_info["server_name"] = "Flask Web Server"
        if "version" not in server_info:
            server_info["version"] = "1.0.0"
        self.file_utils.write_json_file(
            SERVER_INFO_FILE, server_info, ensure_ascii=False, indent=2
        )

    def load_server_info(self):
        return self.file_utils.read_json_file(
            SERVER_INFO_FILE,
            default={
                "server_name": "Flask Web Server",
                "start_time": None,
                "version": "1.0.0",
            },
        )

    def save_server_info(self, info):
        self.file_utils.write_json_file(
            SERVER_INFO_FILE, info, ensure_ascii=False, indent=2
        )

    def get_uptime(self):
        server_info = self.load_server_info()
        start_time = server_info.get("start_time")
        if not start_time:
            return "未知"
        try:
            start_dt = datetime.fromisoformat(start_time)
            uptime = datetime.now() - start_dt
            days = uptime.days
            hours = uptime.seconds // 3600
            minutes = (uptime.seconds % 3600) // 60
            if days > 0:
                return f"{days}天 {hours}小时 {minutes}分钟"
            elif hours > 0:
                return f"{hours}小时 {minutes}分钟"
            else:
                return f"{minutes}分钟"
        except Exception:
            return "未知"

    # --- Active Sessions ---
    def load_active_sessions(self):
        return {
            r["username"]: dict(r)
            for r in self.db.query(
                "SELECT username, ip, user_agent, last_activity FROM active_sessions"
            )
        }

    def save_active_sessions(self, sessions):
        with self.db.transaction():
            self.db.execute("DELETE FROM active_sessions")
            rows = [
                (
                    s["username"],
                    s.get("ip", ""),
                    s.get("user_agent", ""),
                    s.get("last_activity", ""),
                )
                for s in sessions.values()
            ]
            self.db.executemany(
                "INSERT INTO active_sessions (username, ip, user_agent, last_activity) VALUES (?,?,?,?)",
                rows,
            )

    def update_active_session(self, username, ip, user_agent):
        now = datetime.now().isoformat()
        active_sessions = self.load_active_sessions()
        active_sessions[username] = {
            "username": username,
            "ip": ip,
            "user_agent": user_agent,
            "last_activity": now,
        }
        self.save_active_sessions(active_sessions)

    def cleanup_old_sessions(self):
        now = datetime.now()
        timeout = timedelta(minutes=30)
        active_sessions = self.load_active_sessions()
        expired_users = []
        for username, session_data in list(active_sessions.items()):
            try:
                last_activity = datetime.fromisoformat(session_data["last_activity"])
                if now - last_activity > timeout:
                    expired_users.append(username)
            except Exception:
                expired_users.append(username)
        for username in expired_users:
            del active_sessions[username]
        self.save_active_sessions(active_sessions)

    def get_active_sessions(self):
        return self.load_active_sessions()

    # --- User Management ---
    def toggle_user_status(self, username, current_username=None):
        if current_username == username:
            return (False, "不能禁用自己")
        users = self.user_utils.load_users()
        if username not in users:
            return (False, "用户不存在")
        user = users[username]
        if is_superadmin(user):
            return (False, "不能禁用超级管理员")
        user["enabled"] = not user["enabled"]
        self.user_utils.save_users(users)
        action = "启用" if user["enabled"] else "禁用"
        self.user_utils.add_activity(
            username=current_username,
            description=f"{action}用户：{username}",
            ip="",
            path="",
            user_agent="",
            is_logged_in=True,
        )
        return (True, f"用户已{action}")

    def register_user(self, username, password, role="user", uid=None):
        """
        注册新用户（ADR-0007：UID 分区落段校验 + 手动指定 UID）。

        role 允许 {user, api, admin}（未来新增身份在此扩展）。
        uid 为 None 时自动分配：admin 从 11 起、其余从 1001 起取首个空位。
        uid 非空时手动指定：0-10 为系统保留区拒绝；admin 仅 11-99 合法；
        非 admin 在 uid>=11 合法；占用拒绝。新建用户 is_superadmin 恒为 0。

        Returns:
            tuple: (success, message)
        """
        from werkzeug.security import generate_password_hash

        if role not in ("user", "api", "admin"):
            return (False, f"不支持的角色: {role}")

        users = self.user_utils.load_users()
        if username in users:
            return (False, "用户名已存在")
        used_ids = {u.get("id", 0) for u in users.values()}

        if uid is None:
            if role == "admin":
                new_id = self._first_free(11, 99, used_ids)
                if new_id is None:
                    return (False, "管理员 UID 段（11-99）已满")
            else:
                new_id = self._first_free_nonadmin(used_ids)
        else:
            try:
                new_id = int(uid)
            except (TypeError, ValueError):
                return (False, "UID 必须是整数")
            if new_id < 0:
                return (False, "UID 不能为负")
            if new_id <= 10:
                return (False, "UID 0-10 为系统保留区，不可指定")
            if role == "admin" and not (11 <= new_id <= 99):
                return (False, "管理员的 UID 必须在 11-99 之间")
            if new_id in used_ids:
                return (False, f"UID {new_id} 已被占用")

        users[username] = {
            "id": new_id,
            "username": username,
            "password": generate_password_hash(password),
            "role": role,
            "enabled": True,
            "is_superadmin": 0,
        }
        self.user_utils.save_users(users)
        return (True, "注册成功")

    @staticmethod
    def _first_free(lo, hi, used_ids):
        """[lo, hi] 内首个未占用 id，无则 None"""
        for i in range(lo, hi + 1):
            if i not in used_ids:
                return i
        return None

    @staticmethod
    def _first_free_nonadmin(used_ids):
        """非 admin 自动分配：从 max(1001, max_id+1) 起向上取首个空位（避开 100-1000 保留段）"""
        max_id = max(used_ids) if used_ids else 0
        i = max(1001, max_id + 1)
        while i in used_ids:
            i += 1
        return i

    def delete_user(self, username, current_username=None):
        if current_username == username:
            return (False, "不能删除自己")
        users = self.user_utils.load_users()
        if username not in users:
            return (False, "用户不存在")
        user = users[username]
        if is_superadmin(user):
            return (False, "不能删除超级管理员")
        del users[username]
        self.user_utils.save_users(users)
        return (True, "删除成功")

    def get_user_list(self):
        users = self.user_utils.load_users()
        return list(users.values())

    # --- Config Management ---
    def get_config(self):
        return self.config_utils.load_config()

    def update_config(self, new_config):
        """
        更新配置（键白名单 + 路径校验，恢复 aff91cf S4 / dcdcdc9 M39 /
        历史键白名单；原实现为 current.update(new_config) 裸合并，
        任意顶层键可写入且路径无校验，ADR-0006 恢复）

        Returns:
            tuple: (success, message)
        """
        if not isinstance(new_config, dict):
            return (False, "无效的配置格式")

        unknown_keys = set(new_config.keys()) - set(ALLOWED_CONFIG_KEYS.keys())
        if unknown_keys:
            return (
                False,
                "不允许更新以下配置项: " + ", ".join(sorted(unknown_keys)),
            )

        # 路径配置：子键白名单 + 空值/类型/存在性校验（逐键合并，保留既有键）
        if "paths" in new_config:
            paths_update = new_config["paths"]
            if not isinstance(paths_update, dict):
                return (False, "paths 必须是对象")
            for key, value in paths_update.items():
                if key not in ALLOWED_CONFIG_KEYS["paths"]:
                    return (False, f"不允许的配置键: paths.{key}")
                # S4: 路径值校验 - 空值/null 检查
                if value is None or (isinstance(value, str) and not value.strip()):
                    return (False, f"路径 {key} 不能为空")
                # 类型验证：必须是字符串
                if not isinstance(value, str):
                    return (False, f"路径 {key} 必须是字符串类型")
                # M39: 路径存在性验证（相对路径相对项目根）
                path_to_check = Path(value)
                if not path_to_check.is_absolute():
                    path_to_check = BASE_DIR / path_to_check
                if not path_to_check.exists():
                    return (False, f"路径不存在: {value}（{key}）")

        # 壁纸配置：子键白名单 + 类型/空值校验
        if "wallpaper" in new_config:
            wallpaper_update = new_config["wallpaper"]
            if not isinstance(wallpaper_update, dict):
                return (False, "wallpaper 必须是对象")
            for key, value in wallpaper_update.items():
                if key not in ALLOWED_CONFIG_KEYS["wallpaper"]:
                    return (False, f"不允许的配置键: wallpaper.{key}")
                if key == "path" and (
                    value is None or (isinstance(value, str) and not value.strip())
                ):
                    return (False, "壁纸路径不能为空")
                if key == "enabled" and not isinstance(value, bool):
                    return (False, "wallpaper.enabled 必须是布尔值")
                if key == "path" and not isinstance(value, str):
                    return (False, "wallpaper.path 必须是字符串类型")

        # 挂载页面：数组类型 + 数量上限
        if "mounted_pages" in new_config:
            pages = new_config["mounted_pages"]
            if not isinstance(pages, list):
                return (False, "mounted_pages 必须是数组")
            if len(pages) > MAX_MOUNTED_PAGES:
                return (
                    False,
                    f"挂载页面数量不能超过{MAX_MOUNTED_PAGES}个",
                )

        self.config_utils.backup_config()
        current = self.config_utils.load_config()
        # 逐子键合并：paths/wallpaper 保留未提交的既有键，mounted_pages 整体替换
        for key, value in new_config.items():
            if key in ("paths", "wallpaper") and isinstance(value, dict):
                current.setdefault(key, {}).update(value)
            else:
                current[key] = value
        self.config_utils.save_config(current)
        return (True, "配置已更新")

    # --- Settings Management ---
    def get_settings(self):
        """
        获取所有开关设置（委托 common.settings_utils，保留管理后台调用 API）

        Returns:
            dict: settings 字典，缺省值补全
        """
        from Module.common.settings_utils import get_settings

        return get_settings()

    def update_setting(self, key, value):
        """
        更新单个开关设置（委托 common.settings_utils）

        Returns:
            tuple: (success, message)
        """
        from Module.common.settings_utils import update_setting

        return update_setting(key, value)

    def is_feature_enabled(self, feature_key):
        """
        检查功能是否启用（委托 common.settings_utils，保留管理后台调用 API）

        Returns:
            bool: 是否启用（默认 True）
        """
        from Module.common.settings_utils import is_feature_enabled

        return is_feature_enabled(feature_key)

    # --- Mounted Pages ---
    def get_mounted_pages(self):
        """
        读取挂载页面列表（对旧格式记录做类型回退推断）

        旧格式记录（手工编辑 config.json 或旧版本写入）可能缺 type 键甚至只有
        is_file 键；前端 config.html 按 page.type === 'file' 渲染类型列，缺 type
        会全部误判为"目录"。对返回值做规范化（I4）：
        - 有 type 键 → 原样保留；
        - 无 type 有 is_file → 推断 is_file ? "file" : "directory"；
        - 两者都无 → 默认 "file"（与 index.py 挂载服务"缺省倾向按文件处理"
          （is_file 兜底 + page_path.is_file()）的口径一致）。
        规范化只作用于返回值，不写回 config.json（避免破坏用户手工格式）。
        """
        config = self.config_utils.load_config()
        pages = config.get("mounted_pages", [])
        normalized = []
        for page in pages:
            if not isinstance(page, dict):
                normalized.append(page)
                continue
            if "type" in page:
                normalized.append(page)
                continue
            if "is_file" in page:
                page_type = "file" if page.get("is_file") else "directory"
            else:
                page_type = "file"
            normalized.append(
                {
                    "name": page.get("name"),
                    "path": page.get("path"),
                    "type": page_type,
                }
            )
        return normalized

    def add_mounted_page(self, name, path, page_type="file"):
        """
        添加挂载页面（恢复历史 admin.py 校验：名称格式/路径存在性/系统敏感
        路径白名单/文件必须 HTML/数量上限/重名，ADR-0006）

        Returns:
            tuple: (success, message)
        """
        # 名称格式：仅允许 ASCII 字母/数字/下划线/短横线（isalnum 会放行中文）
        if not name or not re.fullmatch(r"[A-Za-z0-9_-]+", name):
            return (False, "名称只能包含字母、数字、下划线和短横线")

        if not path or not str(path).strip():
            return (False, "路径不能为空")

        # 路径存在性（支持相对项目根目录的相对路径）
        raw_path = Path(path)
        file_path = raw_path if raw_path.is_absolute() else BASE_DIR / raw_path
        if not file_path.exists():
            return (False, f"路径不存在: {path}")

        # 系统敏感路径白名单：禁止挂载（a4713d4 H13）
        resolved_file = file_path.resolve()
        for sensitive in SENSITIVE_PATHS:
            try:
                resolved_file.relative_to(Path(sensitive).resolve())
                return (False, f"禁止挂载系统敏感路径: {sensitive}")
            except ValueError:
                continue

        # 文件挂载仅支持 HTML 文件
        if file_path.is_file() and file_path.suffix.lower() != ".html":
            return (
                False,
                f"文件挂载仅支持HTML文件，当前文件类型: {file_path.suffix}",
            )

        config = self.config_utils.load_config()
        pages = config.get("mounted_pages", [])

        # 数量上限
        if len(pages) >= MAX_MOUNTED_PAGES:
            return (False, f"挂载页面数量已达上限（{MAX_MOUNTED_PAGES}个）")

        # 重名检查
        for page in pages:
            if page.get("name") == name:
                return (False, f'名称 "{name}" 已存在，请使用其他名称')

        if "mounted_pages" not in config:
            config["mounted_pages"] = []
        config["mounted_pages"].append({"name": name, "path": path, "type": page_type})
        self.config_utils.save_config(config)
        return (True, "挂载成功")

    def remove_mounted_page(self, name):
        """
        删除挂载页面（恢复"页面不存在"判定，历史 admin.py 行为，ADR-0006）

        Returns:
            tuple: (success, message)
        """
        config = self.config_utils.load_config()
        pages = config.get("mounted_pages", [])
        remaining = [p for p in pages if p.get("name") != name]
        if len(remaining) == len(pages):
            return (False, "页面不存在")
        config["mounted_pages"] = remaining
        self.config_utils.save_config(config)
        return (True, "删除成功")

    # --- IP Utility ---
    @staticmethod
    def get_real_ip(req):
        """客户端真实 IP（委托 common.net_utils，保留方法签名兼容路由层调用）"""
        from Module.common.net_utils import get_client_ip

        return get_client_ip(req)
