"""
ipguard rate_limiter 单元测试
"""

import time

from Module.ipguard import rate_limiter


def setup_function():
    rate_limiter.reset_state()


def test_first_line_window_count():
    """登录场景滑窗计数在 60 秒窗口内正确累计"""
    now = 1_000_000.0
    rate_limiter.record_access("1.1.1.1", bucket="login", now=now)
    rate_limiter.record_access("1.1.1.1", bucket="login", now=now + 30)
    assert rate_limiter.count_in_window("1.1.1.1", "login", 60, now + 31) == 2


def test_first_line_window_expired_records_ignored():
    """超过一小时窗口的旧记录不计入"""
    now = 1_000_000.0
    rate_limiter.record_access("1.1.1.1", bucket="login", now=now - 4000)
    rate_limiter.record_access("1.1.1.1", bucket="login", now=now)
    assert rate_limiter.count_in_window("1.1.1.1", "login", 3600, now) == 1


def test_limit_arrived_login():
    """登录：1分钟>5次 或 1小时>15次 触发"""
    now = 1_000_000.0
    for i in range(6):
        rate_limiter.record_access("1.1.1.1", bucket="login", now=now + i)
    assert rate_limiter.exceed_limits("1.1.1.1", "login", now + 6) is True


def test_limit_not_arrived_login():
    """登录：1分钟5次未超过阈值"""
    now = 1_000_000.0
    for i in range(5):
        rate_limiter.record_access("1.1.1.1", bucket="login", now=now + i)
    assert rate_limiter.exceed_limits("1.1.1.1", "login", now + 6) is False


def test_limit_arrived_ua():
    """UA场景：1分钟>3次触发"""
    now = 1_000_000.0
    for i in range(4):
        rate_limiter.record_access("1.1.1.1", bucket="ua", now=now + i)
    assert rate_limiter.exceed_limits("1.1.1.1", "ua", now + 4) is True


def test_line2_path_over_limit():
    """第二防线：同一IP+同一path 1分钟>10次"""
    now = 1_000_000.0
    ok = False
    for i in range(12):
        ok = rate_limiter.record_path_access("1.1.1.1", "/book/view", now=now + i)
    assert ok is True


def test_line2_path_within_limit():
    """第二防线：10次以内不触发"""
    now = 1_000_000.0
    ok = False
    for i in range(10):
        ok = rate_limiter.record_path_access("1.1.1.1", "/book/view", now=now + i)
    assert ok is False


def test_line2_trigger_first_returns_rate_limited():
    """第二防线第1次触发 -> rate_limited"""
    now = 1_000_000.0
    action = rate_limiter.handle_line2_trigger("1.1.1.1", now=now)
    assert action == "rate_limited"
    assert rate_limiter.in_line2_rate_limit("1.1.1.1", now=now + 30) is True


def test_line2_trigger_second_within_10min_returns_ban():
    """第二防线10分钟内第2次触发 -> ban_2min"""
    now = 1_000_000.0
    rate_limiter.handle_line2_trigger("1.1.1.1", now=now)
    # 第1次限速解除后再次触发（仍在10分钟窗口内）
    action = rate_limiter.handle_line2_trigger("1.1.1.1", now=now + 120)
    assert action == "ban_2min"


def test_line2_trigger_third_returns_permanent():
    """第二防线第3次触发 -> permanent"""
    now = 1_000_000.0
    rate_limiter.handle_line2_trigger("1.1.1.1", now=now)
    rate_limiter.handle_line2_trigger("1.1.1.1", now=now + 120)
    action = rate_limiter.handle_line2_trigger("1.1.1.1", now=now + 240)
    assert action == "permanent"


def test_line2_trigger_reset_after_10min():
    """第二防线超过10分钟窗口后触发次数重置"""
    now = 1_000_000.0
    rate_limiter.handle_line2_trigger("1.1.1.1", now=now)
    action = rate_limiter.handle_line2_trigger("1.1.1.1", now=now + 60 * 11)
    assert action == "rate_limited"


def test_trim_prunes_empty_window_key():
    """窗口内记录全部过期后空键被删除，防键集无界增长"""
    now = 10_000_000.0
    rate_limiter._records[("login", "1.1.1.1")] = [now - 4000, now - 3900]
    rate_limiter._trim(("login", "1.1.1.1"), now=now)
    assert ("login", "1.1.1.1") not in rate_limiter._records
    assert rate_limiter.count_in_window("1.1.1.1", "login", 3600, now) == 0
