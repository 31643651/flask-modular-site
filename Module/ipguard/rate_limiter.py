"""
ipguard 频率检查核心逻辑

维护内存滑动窗口用于实时频率计数：
- 第一防线：login（未登录访问 /user/login）与 ua（UA 为 Other）两个独立滑窗
- 第二防线：按 (ip, path) 统计 1 分钟窗口内的页面 GET 访问
- 第二防线限速状态：trigger_count / last_trigger / expires
"""

import threading
import time

# --- 阈值常量 ---
# 第一防线：未登录访问 /user/login
LOGIN_MINUTE_LIMIT = 5
LOGIN_HOUR_LIMIT = 15
# 第一防线：UA 浏览器或 OS 为 Other
UA_MINUTE_LIMIT = 3
UA_HOUR_LIMIT = 9
# 第二防线：同一路径 1 分钟上限
PATH_MINUTE_LIMIT = 10
# 第二防线：限速时长（秒）
LINE2_RATE_LIMIT_SECONDS = 60
# 第二防线：10 分钟窗口（秒）
LINE2_WINDOW_SECONDS = 600

# 内存滑窗：bucket_key -> (ip -> [时间戳])
# bucket_key 为 "login" / "ua" / ("path", path)
_records = {}
_records_lock = threading.RLock()

# 第二防线限速状态：ip -> {"trigger_count": int, "last_trigger": float, "expires": float}
_line2_state = {}
_line2_lock = threading.RLock()

# 滑窗保留上限（防止内存无限膨胀）与裁剪窗口
MAX_RECORDS_PER_KEY = 200
RECORD_WINDOW_SECONDS = 3600


def reset_state():
    """测试辅助：清空所有内存状态"""
    global _records, _line2_state
    with _records_lock:
        _records = {}
    with _line2_lock:
        _line2_state = {}


def _trim(key, now):
    """裁剪：仅保留一小时内的记录，超出上限截断；空窗口删除键防键集膨胀"""
    cutoff = now - RECORD_WINDOW_SECONDS
    recs = _records[key]
    recs = [t for t in recs if t > cutoff]
    if len(recs) > MAX_RECORDS_PER_KEY:
        recs = recs[-MAX_RECORDS_PER_KEY:]
    if not recs:
        del _records[key]
    else:
        _records[key] = recs


def record_access(ip, bucket, now=None):
    """第一防线：记录一次访问到指定滑窗（login / ua）"""
    now = now if now is not None else time.time()
    key = (bucket, ip)
    with _records_lock:
        recs = _records.setdefault(key, [])
        recs.append(now)
        _trim(key, now)


def count_in_window(ip, bucket, seconds, now=None):
    """第一防线：统计某滑窗在最近 seconds 秒内的访问次数"""
    now = now if now is not None else time.time()
    key = (bucket, ip)
    with _records_lock:
        recs = list(_records.get(key, []))
    cutoff = now - seconds
    return sum(1 for t in recs if t > cutoff)


def exceed_limits(ip, bucket, now=None):
    """第一防线：判断是否达到阈值（1 分钟或 1 小时任一超限即触发）"""
    now = now if now is not None else time.time()
    if bucket == "login":
        min_limit, hour_limit = LOGIN_MINUTE_LIMIT, LOGIN_HOUR_LIMIT
    elif bucket == "ua":
        min_limit, hour_limit = UA_MINUTE_LIMIT, UA_HOUR_LIMIT
    else:
        raise ValueError(f"未知 bucket: {bucket}")
    minute_count = count_in_window(ip, bucket, 60, now)
    hour_count = count_in_window(ip, bucket, 3600, now)
    return minute_count > min_limit or hour_count > hour_limit


def record_path_access(ip, path, now=None):
    """第二防线：记录一次页面 GET 访问，返回是否超过 1 分钟阈值"""
    now = now if now is not None else time.time()
    key = ("path", ip, path)
    with _records_lock:
        recs = _records.setdefault(key, [])
        recs.append(now)
        _trim(key, now)
    cutoff = now - 60
    return sum(1 for t in recs if t > cutoff) > PATH_MINUTE_LIMIT


def handle_line2_trigger(ip, now=None):
    """
    第二防线触发：返回动作名
    - "rate_limited"：第1次，进入 1 分钟限速
    - "ban_2min"：第2次（10 分钟窗口内），封禁 2 分钟
    - "permanent"：第3次及以上，永久封禁
    """
    now = now if now is not None else time.time()
    with _line2_lock:
        st = _line2_state.get(ip)
        if not st:
            st = {"trigger_count": 0, "last_trigger": 0, "expires": 0}
        if now - st["last_trigger"] > LINE2_WINDOW_SECONDS:
            st["trigger_count"] = 0
        st["trigger_count"] += 1
        st["last_trigger"] = now
        st["expires"] = now + LINE2_RATE_LIMIT_SECONDS
        _line2_state[ip] = st
        count = st["trigger_count"]
    if count == 1:
        return "rate_limited"
    if count == 2:
        return "ban_2min"
    return "permanent"


def in_line2_rate_limit(ip, now=None):
    """第二防线：当前是否处于 1 分钟限速期内"""
    now = now if now is not None else time.time()
    with _line2_lock:
        st = _line2_state.get(ip)
        if not st:
            return False
        return st["expires"] > now
