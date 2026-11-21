"""
ipguard 封禁管理逻辑

- 内存缓存 _ban_cache（启动时从 SQLite 加载），实时判断免查库
- 封禁结果持久化到 ip_bans 表
- 第一防线：递进式封禁（5分钟/1小时/24小时/永久，24小时窗口重置）
- 第二防线：impose_time_ban（2分钟）/ impose_permanent_ban（永久）
"""

import threading
import time
from datetime import datetime

from Module.common import db_utils

# 第一防线递进封禁时长（第 N 次 -> 秒）
PROGRESSIVE_BAN_SECONDS = {1: 300, 2: 3600, 3: 86400}
PERMANENT_BAN_COUNT = 4
BAN_RESET_HOURS = 24

BAN_REASON_LABELS = {
    "line1_login": "第一防线（登录频率）",
    "line1_illegal_ua": "第一防线（异常UA）",
    "line2_rate": "第二防线（页面频率）",
}

_ban_cache = {}
_ban_lock = threading.RLock()


def _fmt_ts(ts):
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def _parse_ts(s):
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").timestamp()
    except (TypeError, ValueError):
        return 0


def reset_state():
    """测试辅助：清空内存缓存（不影响数据库）"""
    global _ban_cache
    with _ban_lock:
        _ban_cache = {}


def load_ban_cache():
    """从 SQLite 加载全部封禁到内存缓存（启动时调用）"""
    global _ban_cache
    rows = db_utils.query("SELECT * FROM ip_bans")
    with _ban_lock:
        _ban_cache = {}
        for r in rows:
            _ban_cache[r["ip"]] = {
                "ban_count": r["ban_count"],
                "ban_reason": r["ban_reason"],
                "created_at": r["created_at"],
                "expires_at": _parse_ts(r["expires_at"]) if r["expires_at"] else None,
                "is_permanent": bool(r["is_permanent"]),
            }


def _write_ban(ip, data):
    """
    写入内存缓存与 SQLite（幂等、并发安全）

    DB 采用单条 UPSERT（INSERT ... ON CONFLICT(ip) DO UPDATE），消除
    SELECT 与 UPDATE/INSERT 之间的 TOCTOU 竞态：并发首触同一 IP 不再
    双双读到"无记录"而双 INSERT 触发 IntegrityError，导致封禁不落库。
    内存缓存先写入，再持久化，保证实时判定与落库语义一致。
    """
    with _ban_lock:
        _ban_cache[ip] = data
    db_utils.execute(
        "INSERT INTO ip_bans (ip, ban_count, ban_reason, created_at, expires_at, is_permanent) "
        "VALUES (?,?,?,?,?,?) "
        "ON CONFLICT(ip) DO UPDATE SET "
        "ban_count=excluded.ban_count, ban_reason=excluded.ban_reason, "
        "created_at=excluded.created_at, expires_at=excluded.expires_at, "
        "is_permanent=excluded.is_permanent",
        (
            ip,
            data["ban_count"],
            data["ban_reason"],
            data["created_at"],
            _fmt_ts(data["expires_at"]) if data["expires_at"] else None,
            1 if data["is_permanent"] else 0,
        ),
    )


def get_ban(ip):
    """返回封禁状态 dict；不存在返回 None"""
    with _ban_lock:
        return _ban_cache.get(ip)


def _active_ban(ip, now):
    """返回 (is_active, remaining_seconds)；过期记录自动清理"""
    ban = get_ban(ip)
    if not ban:
        return False, None
    if ban["is_permanent"]:
        return True, None
    if ban["expires_at"] and now < ban["expires_at"]:
        return True, int(ban["expires_at"] - now)
    # 过期：封禁态失效。距上次封禁 <24h 时保留 ban_count/created_at 供递进升级；
    # 超过 24h 后计数不再影响升级，删除记录防键集/行无限膨胀。
    last_ts = _parse_ts(ban.get("created_at"))
    if last_ts and now - last_ts >= BAN_RESET_HOURS * 3600:
        with _ban_lock:
            _ban_cache.pop(ip, None)
        db_utils.execute("DELETE FROM ip_bans WHERE ip = ?", (ip,))
    return False, None


def is_ip_banned(ip, now=None):
    """检查 ip 是否处于封禁中。返回 (banned, remaining_seconds)。永久封禁 remaining 为 None。"""
    now = now if now is not None else time.time()
    return _active_ban(ip, now)


def execute_progressive_ban(ip, reason, now=None):
    """
    第一防线递进式封禁

    返回本次封禁结果 dict：{ban_count, ban_reason, created_at, expires_at,
    is_permanent, remaining_seconds}
    """
    now = now if now is not None else time.time()
    existing = get_ban(ip)
    ban_count = 1
    created_at = _fmt_ts(now)
    if existing:
        # 已永久封禁时保持永久
        if existing["is_permanent"]:
            return {
                **existing,
                "remaining_seconds": None,
            }
        last_ts = _parse_ts(existing["created_at"])
        if last_ts and now - last_ts < BAN_RESET_HOURS * 3600:
            ban_count = existing["ban_count"] + 1
            # 仍处于 24h 窗口内：更新锚点为本次触发时间，使比较基准为"距上次封禁"
            created_at = _fmt_ts(now)

    if ban_count >= PERMANENT_BAN_COUNT:
        data = {
            "ban_count": ban_count,
            "ban_reason": reason,
            "created_at": created_at,
            "expires_at": None,
            "is_permanent": True,
        }
        remaining = None
    else:
        ban_seconds = PROGRESSIVE_BAN_SECONDS.get(ban_count, PROGRESSIVE_BAN_SECONDS[1])
        data = {
            "ban_count": ban_count,
            "ban_reason": reason,
            "created_at": created_at,
            "expires_at": now + ban_seconds,
            "is_permanent": False,
        }
        remaining = int(ban_seconds)
    _write_ban(ip, data)
    return {**data, "remaining_seconds": remaining}


def impose_time_ban(ip, seconds, reason="line2_rate", now=None):
    """第二防线第2次：封禁指定秒数（不影响第一防线次数累计）"""
    now = now if now is not None else time.time()
    existing = get_ban(ip)
    if existing and existing["is_permanent"]:
        return {**existing, "remaining_seconds": None}
    data = {
        "ban_count": existing["ban_count"] if existing else 1,
        "ban_reason": reason,
        "created_at": existing["created_at"] if existing else _fmt_ts(now),
        "expires_at": now + seconds,
        "is_permanent": False,
    }
    _write_ban(ip, data)
    return {**data, "remaining_seconds": int(seconds)}


def impose_permanent_ban(ip, reason="line2_rate", now=None):
    """第二防线第3次：永久封禁"""
    now = now if now is not None else time.time()
    existing = get_ban(ip)
    data = {
        "ban_count": existing["ban_count"] if existing else 1,
        "ban_reason": reason,
        "created_at": existing["created_at"] if existing else _fmt_ts(now),
        "expires_at": None,
        "is_permanent": True,
    }
    _write_ban(ip, data)
    return {**data, "remaining_seconds": None}


def unban(ip):
    """手动解除封禁：删除缓存与数据库记录"""
    with _ban_lock:
        _ban_cache.pop(ip, None)
    db_utils.execute("DELETE FROM ip_bans WHERE ip = ?", (ip,))


def get_active_bans(now=None):
    """
    返回活跃封禁列表（未过期或永久），按 id 倒序

    每条含：id, ip, ban_count, ban_reason_label, created_at, expires_at,
    is_permanent, remaining_seconds
    """
    now = now if now is not None else time.time()
    rows = db_utils.query("SELECT * FROM ip_bans ORDER BY id DESC")
    result = []
    for r in rows:
        permanent = bool(r["is_permanent"])
        expires_ts = _parse_ts(r["expires_at"]) if r["expires_at"] else None
        if not permanent and (not expires_ts or now >= expires_ts):
            continue
        item = dict(r)
        item["ban_reason_label"] = BAN_REASON_LABELS.get(
            r["ban_reason"], r["ban_reason"]
        )
        item["is_permanent"] = permanent
        item["remaining_seconds"] = None if permanent else int(expires_ts - now)
        result.append(item)
    return result
