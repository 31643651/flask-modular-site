"""
用户工具模块

提供用户数据读取和活动日志记录等共享功能。
所有高频可变数据（用户、活动日志）统一存储于 SQLite。
用户数据带 TTL 缓存减少高频读 IO，活动日志走内存队列异步批量写入。
"""

import atexit
import hmac
import re
import secrets
import threading
import time
import structlog
from datetime import datetime
from flask import session, redirect, url_for
from werkzeug.security import check_password_hash, generate_password_hash
from .db_utils import query, execute, executemany, transaction

# 用户缓存（TTL 30 秒）
_users_cache = None
_users_cache_ts = 0.0
_users_cache_lock = threading.Lock()
USER_CACHE_TTL = 30

# 活动日志异步队列（线程安全）
_activity_queue = []  # 每项为 dict（含 username/description/time/ip/path/device_type/os/browser/is_logged_in）
_activity_queue_lock = threading.Lock()
_ACTIVITY_FLUSH_INTERVAL = 10  # 后台 flush 间隔（秒）
_activity_flush_thread = None


def flush_activity_queue():
    """
    将内存队列中的活动日志批量写入 SQLite（线程安全，幂等）

    供后台线程定时调用、程序退出（atexit）及服务器重启前调用。
    """
    global _activity_queue
    with _activity_queue_lock:
        if not _activity_queue:
            return
        pending = _activity_queue
        _activity_queue = []

    if not pending:
        return

    rows = [
        (
            a.get("username", ""),
            a.get("description", ""),
            a.get("time", ""),
            a.get("ip", ""),
            a.get("path", ""),
            a.get("device_type", ""),
            a.get("os", ""),
            a.get("browser", ""),
            1 if a.get("is_logged_in", False) else 0,
        )
        for a in pending
    ]
    try:
        with transaction():
            executemany(
                "INSERT INTO activity_log (username, description, time, ip, path, device_type, os, browser, is_logged_in) VALUES (?,?,?,?,?,?,?,?,?)",
                rows,
            )
    except Exception:
        # 写入失败时把已取出的记录放回队首，避免静默丢失；由后续 flush 重试
        with _activity_queue_lock:
            _activity_queue = pending + _activity_queue
        raise


def _activity_flush_worker():
    """后台守护线程：每 10 秒尝试将队列批量写入 SQLite"""
    logger = structlog.get_logger(__name__)
    while True:
        time.sleep(_ACTIVITY_FLUSH_INTERVAL)
        try:
            flush_activity_queue()
        except Exception:
            # 失败回填已在 flush_activity_queue 内部完成，这里仅记录错误；
            # 后台线程不允许因单次异常退出，继续循环
            logger.error("activity_flush_failed")


def _ensure_flush_thread():
    """确保后台 flush 线程已启动（懒启动，避免无活动日志时白开线程）"""
    global _activity_flush_thread
    if _activity_flush_thread is not None:
        return
    with _activity_queue_lock:
        if _activity_flush_thread is not None:
            return
        _activity_flush_thread = threading.Thread(
            target=_activity_flush_worker, daemon=True
        )
        _activity_flush_thread.start()
        # 解释器正常退出时强制落盘，避免 daemon 线程被直接终止丢失队列数据
        # 双检锁保证此处每进程仅执行一次
        atexit.register(flush_activity_queue)


def load_users():
    """
    从 SQLite 加载用户数据（TTL 缓存 30 秒）

    Returns:
        dict: 用户字典，key 为用户名
    """
    global _users_cache, _users_cache_ts
    now = time.time()
    with _users_cache_lock:
        if _users_cache is not None and now - _users_cache_ts < USER_CACHE_TTL:
            return _users_cache
    logger = structlog.get_logger(__name__)
    if _users_cache is not None:
        logger.debug("users_cache_expired", cache_age=now - _users_cache_ts)
    rows = query(
        "SELECT id, username, password, role, enabled, is_superadmin FROM users"
    )
    users = {
        r["username"]: {
            "id": r["id"],
            "username": r["username"],
            "password": r["password"],
            "role": r["role"],
            "enabled": bool(r["enabled"]),
            "is_superadmin": bool(r["is_superadmin"]),
        }
        for r in rows
    }
    with _users_cache_lock:
        _users_cache = users
        _users_cache_ts = time.time()
    return users


def invalidate_users_cache():
    """
    使缓存立即失效（注册/删除/禁用用户后调用，save_users 内部也会调用）

    注意：本函数不清空数据库，仅清除内存缓存，下次 load_users 重新读库。
    """
    global _users_cache, _users_cache_ts
    with _users_cache_lock:
        _users_cache = None
        _users_cache_ts = 0.0


def ensure_admin_exists():
    """
    启动期 admin 账户常驻兜底（ADR-0003 + ADR-0007 对齐 0-9）：

    保证兜底产生的超管永远落在 0-9 最小空位（避免被 R2 越界清退禁用）：
    - username='admin' 行存在：
        - 已可用（role=admin 且 enabled 且 is_superadmin）且 id 在 0-9 → 不动
        - 不可用且 id 已在 0-9 → 原地恢复 role/enabled/is_superadmin
        - 不可用且 id>9 → 重定位其行到 0-9 最小空位（用户名/密码保留，role 修正）
    - 无 admin 行但已有可用超管（改名后）→ 不动
    - 无 admin 行且无可用超管 → 把最老用户重定位到 0-9 最小空位并提权
    - users 表为空 → 在 0-9 最小空位创建 admin（随机密码哈希入库，明文打启动日志）

    仅在 config.json 已存在（非首次部署）时由 create_app 调用；
    首次部署的 admin 创建由 setup 向导负责。

    Returns:
        str: "exists" / "restored" / "promoted" / "created"
    """
    logger = structlog.get_logger(__name__)
    rows = query(
        "SELECT id, username, password, role, enabled, is_superadmin FROM users ORDER BY id ASC"
    )

    def _usable(u):
        return u["role"] == "admin" and bool(u["enabled"]) and bool(u["is_superadmin"])

    def _first_free_0to9():
        """0-9 中首个未被占用的 id"""
        used = {u["id"] for u in rows}
        for i in range(10):
            if i not in used:
                return i
        return None

    admin_row = next((u for u in rows if u["username"] == "admin"), None)
    if admin_row is not None:
        if _usable(admin_row) and 0 <= admin_row["id"] <= 9:
            return "exists"
        if 0 <= admin_row["id"] <= 9:
            execute(
                "UPDATE users SET role = 'admin', enabled = 1, is_superadmin = 1 "
                "WHERE id = ?",
                (admin_row["id"],),
            )
            invalidate_users_cache()
            logger.warning("admin_restored", user_id=admin_row["id"])
            return "restored"
        # admin 行 id>9：重定位到 0-9 最小空位
        new_id = _first_free_0to9()
        if new_id is None:
            return "exists"
        execute(
            "UPDATE users SET id = ?, role = 'admin', enabled = 1, is_superadmin = 1 "
            "WHERE id = ?",
            (new_id, admin_row["id"]),
        )
        invalidate_users_cache()
        logger.warning(
            "admin_relocated_to_superadmin_range",
            old_id=admin_row["id"], new_id=new_id,
        )
        return "restored"

    if any(_usable(u) for u in rows):
        return "exists"

    if rows:
        oldest = rows[0]  # ORDER BY id ASC
        target = _first_free_0to9()
        if target is None:
            return "exists"
        if target == oldest["id"]:
            execute(
                "UPDATE users SET role = 'admin', enabled = 1, is_superadmin = 1 "
                "WHERE id = ?",
                (oldest["id"],),
            )
        else:
            execute(
                "UPDATE users SET id = ?, role = 'admin', enabled = 1, is_superadmin = 1 "
                "WHERE id = ?",
                (target, oldest["id"]),
            )
        invalidate_users_cache()
        logger.warning(
            "admin_promoted_from_oldest_user",
            user_id=oldest["id"], username=oldest["username"], new_id=target,
        )
        return "promoted"

    plaintext = secrets.token_urlsafe(16)
    new_id = _first_free_0to9() or 0
    execute(
        "INSERT INTO users (id, username, password, role, enabled, is_superadmin) "
        "VALUES (?, ?, ?, 'admin', 1, 1)",
        (new_id, "admin", generate_password_hash(plaintext)),
    )
    invalidate_users_cache()
    logger.warning(
        "admin_created_with_random_password", username="admin", password=plaintext,
        user_id=new_id,
    )
    return "created"


def save_users(users):
    """
    将用户字典整体写入 SQLite（全量替换）并失效缓存

    Args:
        users: 用户字典，key 为用户名
    """
    with transaction():
        execute("DELETE FROM users")
        rows = [
            (
                u["id"],
                u["username"],
                u["password"],
                u["role"],
                1 if u["enabled"] else 0,
                1 if u.get("is_superadmin") else 0,
            )
            for u in users.values()
        ]
        executemany(
            "INSERT INTO users (id, username, password, role, enabled, is_superadmin) VALUES (?,?,?,?,?,?)",
            rows,
        )
    # 写库后立即失效缓存，保证下次读取为最新数据
    invalidate_users_cache()


def get_user(username):
    """
    获取用户信息

    Args:
        username: 用户名

    Returns:
        dict: 用户信息，如果未找到返回 None
    """
    users = load_users()
    return users.get(username)


def _is_password_hash(stored):
    """
    判断存储的密码值是否已是 werkzeug 哈希格式

    Args:
        stored: 数据库 users 表 password 列的存储值

    Returns:
        bool: 形如 pbkdf2:/scrypt: 开头返回 True
    """
    return isinstance(stored, str) and (
        stored.startswith("pbkdf2:") or stored.startswith("scrypt:")
    )


def verify_user(username, password):
    """
    验证用户登录凭据

    兼容两种存量格式（bug #16 统一密码哈希）：
    - werkzeug 哈希（pbkdf2:/scrypt: 开头）：用 check_password_hash 校验；
    - 明文：常量时间比较，一旦匹配立即把密码列迁移为哈希（登录即迁移）。

    Args:
        username: 用户名
        password: 密码

    Returns:
        dict or None: 用户信息，验证失败返回 None
    """
    # ADR-0005：登录读路径直读 SQLite，绕过 30s TTL 缓存——
    # 带外手工改库（新增/提权/启用/改密）无需等待过期、无需重启即可登录
    rows = query(
        "SELECT id, username, password, role, enabled, is_superadmin FROM users "
        "WHERE username = ?",
        (username,),
    )
    if not rows:
        return None
    r = rows[0]
    user = {
        "id": r["id"],
        "username": r["username"],
        "password": r["password"],
        "role": r["role"],
        "enabled": bool(r["enabled"]),
        "is_superadmin": bool(r["is_superadmin"]),
    }
    if not user["enabled"]:
        return None

    stored = user["password"]
    if not isinstance(stored, str) or not isinstance(password, str):
        return None

    if _is_password_hash(stored):
        if check_password_hash(stored, password):
            return user
        return None

    # 明文存量：常量时间比较，防止时序侧信道
    if hmac.compare_digest(stored.encode("utf-8"), password.encode("utf-8")):
        # 登录即迁移：明文密码升级为 werkzeug 哈希
        logger = structlog.get_logger(__name__)
        try:
            execute(
                "UPDATE users SET password = ? WHERE username = ?",
                (generate_password_hash(password), username),
            )
            invalidate_users_cache()
            logger.info("password_migrated_to_hash", username=username)
        except Exception:
            # 迁移失败不阻塞登录，下次成功登录时会再次尝试迁移
            logger.warning("password_migration_failed", username=username)
        return user

    return None


def load_activities():
    """
    加载活动日志（内存队列 + SQLite 合并，最新在前）

    后台 flush 前，最新记录在内存队列中；持锁合并，避免 flush 插入的记录重复显示。
    """
    with _activity_queue_lock:
        queued = list(_activity_queue)
        # 队列中最后 append 的是最新，倒序后在前
        queued_records = [dict(a) for a in reversed(queued)]
        rows = query("SELECT * FROM activity_log ORDER BY id DESC")
    db_records = []
    for r in rows:
        a = dict(r)
        a["is_logged_in"] = bool(a["is_logged_in"])
        db_records.append(a)

    return queued_records + db_records


def save_activities(activities):
    """
    保存活动日志到 SQLite（全量替换）

    Args:
        activities: 活动记录列表
    """
    global _activity_queue
    # 先把待写队列取走，避免 flush 早退导致全量替换丢数据
    with _activity_queue_lock:
        queued = _activity_queue
        _activity_queue = []
    if queued:
        # 先将队列记录落盘（独立事务），再执行全量替换
        rows = [
            (
                a.get("username", ""),
                a.get("description", ""),
                a.get("time", ""),
                a.get("ip", ""),
                a.get("path", ""),
                a.get("device_type", ""),
                a.get("os", ""),
                a.get("browser", ""),
                1 if a.get("is_logged_in", False) else 0,
            )
            for a in queued
        ]
        with transaction():
            executemany(
                "INSERT INTO activity_log (username, description, time, ip, path, device_type, os, browser, is_logged_in) VALUES (?,?,?,?,?,?,?,?,?)",
                rows,
            )
    with transaction():
        execute("DELETE FROM activity_log")
        rows = [
            (
                a.get("username", ""),
                a.get("description", ""),
                a.get("time", ""),
                a.get("ip", ""),
                a.get("path", ""),
                a.get("device_type", ""),
                a.get("os", ""),
                a.get("browser", ""),
                1 if a.get("is_logged_in", False) else 0,
            )
            for a in activities
        ]
        executemany(
            "INSERT INTO activity_log (username, description, time, ip, path, device_type, os, browser, is_logged_in) VALUES (?,?,?,?,?,?,?,?,?)",
            rows,
        )


def parse_user_agent(user_agent_string):
    """
    解析 User-Agent 字符串，提取设备、操作系统和浏览器信息

    使用正则表达式替代简单字符串匹配，提高解析准确性。

    Args:
        user_agent_string: User-Agent 字符串

    Returns:
        dict: 包含设备、操作系统、浏览器信息的字典
    """
    ua = user_agent_string

    # 检测设备类型（使用正则，忽略大小写）
    device_type = "未知设备"
    if re.search(r"(?i)android", ua):
        device_type = "Android"
    elif re.search(r"(?i)(iphone|ipad|ipod)", ua):
        device_type = "iOS"
    elif re.search(r"(?i)windows", ua):
        device_type = "Windows"
    elif re.search(r"(?i)(macintosh|mac os x)", ua):
        device_type = "Mac"
    elif re.search(r"(?i)linux", ua):
        device_type = "Linux"

    # 检测操作系统
    os_name = "未知操作系统"
    if re.search(r"(?i)android", ua):
        os_name = "Android"
    elif re.search(r"(?i)(iphone|ipad)", ua):
        os_name = "iOS"
    elif re.search(r"(?i)windows nt 10\.0", ua):
        os_name = "Windows 10/11"
    elif re.search(r"(?i)windows nt 6\.1", ua):
        os_name = "Windows 7"
    elif re.search(r"(?i)windows nt 6\.[23]", ua):
        os_name = "Windows 8/8.1"
    elif re.search(r"(?i)windows", ua):
        os_name = "Windows"
    elif re.search(r"(?i)mac os x", ua):
        os_name = "macOS"
    elif re.search(r"(?i)linux", ua):
        os_name = "Linux"

    # 检测浏览器（注意顺序：Edge 必须在 Chrome 之前检测）
    browser = "未知浏览器"
    if re.search(r"(?i)edg/", ua):
        browser = "Edge"
    elif re.search(r"(?i)chrome/", ua) and not re.search(r"(?i)chromium", ua):
        browser = "Chrome"
    elif re.search(r"(?i)firefox/", ua):
        browser = "Firefox"
    elif re.search(r"(?i)safari/", ua) and not re.search(r"(?i)chrome/", ua):
        browser = "Safari"
    elif re.search(r"(?i)(opera|opr)/", ua):
        browser = "Opera"
    elif re.search(r"(?i)(msie|trident/)", ua):
        browser = "Internet Explorer"

    return {"device_type": device_type, "os": os_name, "browser": browser}


def add_activity(username, description, ip, path="", user_agent="", is_logged_in=True):
    """
    添加活动记录到内存队列（异步批量写入 SQLite）

    请求路径只做内存 append，不阻塞不读库；由后台线程每10 秒批量落盘。

    Args:
        username: 用户名
        description: 活动描述
        ip: IP地址
        path: 访问的页面路径
        user_agent: User-Agent 字符串
        is_logged_in: 是否已登录
    """
    # 清理 User-Agent：移除 HTML 特殊字符
    sanitized_ua = re.sub(r'[<>"\'&]', "", user_agent) if user_agent else ""
    device_info = (
        parse_user_agent(sanitized_ua)
        if sanitized_ua
        else {"device_type": "未知设备", "os": "未知操作系统", "browser": "未知浏览器"}
    )

    now = datetime.now()
    record = {
        "username": username if is_logged_in else "未登录",
        "description": description,
        "time": now.strftime("%Y-%m-%d %H:%M:%S"),
        "ip": ip,
        "path": path,
        "device_type": device_info["device_type"],
        "os": device_info["os"],
        "browser": device_info["browser"],
        "is_logged_in": is_logged_in,
    }

    logger = structlog.get_logger(__name__)
    with _activity_queue_lock:
        _activity_queue.append(record)

    _ensure_flush_thread()


def is_superadmin(user):
    """
    判断用户是否为超级管理员

    条件: uid 0-9 并且是管理员账户（role="admin"）

    Args:
        user: 用户信息字典

    Returns:
        bool: 是否为超级管理员
    """
    if not user:
        return False
    return (
        user.get("role") == "admin"
        and user.get("id", -1) >= 0
        and user.get("id", -1) <= 9
    )


def require_superadmin():
    """
    要求超级管理员权限的装饰器

    检查用户是否为超级管理员，不是则返回重定向。
    当管理员验证码关闭时，跳过验证检查。

    Returns:
        redirect: 重定向到登录页、主页或验证页；权限通过返回 None
    """
    if "user_id" not in session:
        return redirect(url_for("user.login"))

    username = session.get("username")
    user = get_user(username)

    # 实时校验：用户必须存在、启用且为超级管理员
    if not user or not user.get("enabled") or not is_superadmin(user):
        session.clear()
        return redirect(url_for("user.login"))

    # 检查管理员验证码是否启用（settings_utils 直接读取，避免 common→core 反向依赖）
    from Module.common.settings_utils import is_feature_enabled

    if not is_feature_enabled("admin_verify_enabled"):
        # 验证码关闭时自动标记为已验证
        session["verified"] = True
        return None

    if not session.get("verified", False):
        return redirect(url_for("user.verify"))

    return None
