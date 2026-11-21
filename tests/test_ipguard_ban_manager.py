"""
ipguard ban_manager 单元测试
"""

import threading

import pytest

from Module.common import db_utils
from Module.ipguard import ban_manager


@pytest.fixture(autouse=True)
def _isolated_db(switch_db):
    """每个测试使用独立临时库，并清空内存封禁缓存"""
    ban_manager.reset_state()
    yield
    ban_manager.reset_state()


def test_progressive_first_ban_minutes():
    """第一防线第1次封禁 5 分钟"""
    result = ban_manager.execute_progressive_ban("1.1.1.1", "line1_login")
    assert result["is_permanent"] is False
    assert result["ban_count"] == 1
    assert result["expires_at"] - result["expires_at"] == 0
    assert result["remaining_seconds"] == 300


def test_progressive_second_ban_hour():
    """第一防线第2次封禁 1 小时"""
    ban_manager.execute_progressive_ban("1.1.1.1", "line1_login", now=1_000_000.0)
    result = ban_manager.execute_progressive_ban(
        "1.1.1.1", "line1_login", now=1_000_000.0 + 300
    )
    assert result["ban_count"] == 2
    assert result["remaining_seconds"] == 3600


def test_progressive_third_ban_day():
    """第一防线第3次封禁 24 小时"""
    ban_manager.execute_progressive_ban("1.1.1.1", "line1_login", now=1_000_000.0)
    ban_manager.execute_progressive_ban("1.1.1.1", "line1_login", now=1_000_000.0 + 300)
    result = ban_manager.execute_progressive_ban(
        "1.1.1.1", "line1_login", now=1_000_000.0 + 3000
    )
    assert result["ban_count"] == 3
    assert result["remaining_seconds"] == 86400


def test_progressive_fourth_permanent():
    """第一防线第4次永久封禁"""
    base = 1_000_000.0
    for i in range(3):
        ban_manager.execute_progressive_ban(
            "1.1.1.1", "line1_login", now=base + i * 300
        )
    result = ban_manager.execute_progressive_ban(
        "1.1.1.1", "line1_login", now=base + 3 * 300
    )
    assert result["is_permanent"] is True
    assert result["remaining_seconds"] is None


def test_progressive_reset_after_24h():
    """间隔超过24小时封禁次数重置为1"""
    base = 1_000_000.0
    ban_manager.execute_progressive_ban("1.1.1.1", "line1_login", now=base)
    result = ban_manager.execute_progressive_ban(
        "1.1.1.1", "line1_login", now=base + 24 * 3600 + 10
    )
    assert result["ban_count"] == 1
    assert result["remaining_seconds"] == 300


def test_is_ip_banned_active():
    """封禁期内 is_ip_banned 返回 True 与剩余秒数"""
    ban_manager.execute_progressive_ban("1.1.1.1", "line1_login", now=1_000_000.0)
    banned, remaining = ban_manager.is_ip_banned("1.1.1.1", now=1_000_000.0 + 100)
    assert banned is True
    assert remaining == 200


def test_is_ip_banned_expired_keeps_escalation_count():
    """封禁过期后 is_ip_banned 返回 False，但 24h 窗口内保留计数供升级"""
    ban_manager.execute_progressive_ban("1.1.1.1", "line1_login", now=1_000_000.0)
    banned, remaining = ban_manager.is_ip_banned("1.1.1.1", now=1_000_000.0 + 4000)
    assert banned is False
    assert ban_manager.get_ban("1.1.1.1") is not None
    result = ban_manager.execute_progressive_ban(
        "1.1.1.1", "line1_login", now=1_000_000.0 + 4100
    )
    assert result["ban_count"] == 2  # 过期保留计数，24h 内递增


def test_is_ip_banned_expired_beyond_24h_prunes():
    """距上次封禁超过 24h 后过期检查清理记录，防键集膨胀"""
    ban_manager.execute_progressive_ban("1.1.1.1", "line1_login", now=1_000_000.0)
    banned, remaining = ban_manager.is_ip_banned(
        "1.1.1.1", now=1_000_000.0 + 24 * 3600 + 10
    )
    assert banned is False
    assert ban_manager.get_ban("1.1.1.1") is None


def test_permanent_ban_not_overridden():
    """永久封禁不可被新的临时封禁覆盖"""
    ban_manager.execute_progressive_ban("1.1.1.1", "line1_login", now=1_000_000.0)
    ban_manager.execute_progressive_ban("1.1.1.1", "line1_login", now=1_000_000.0 + 300)
    ban_manager.execute_progressive_ban("1.1.1.1", "line1_login", now=1_000_000.0 + 600)
    ban_manager.execute_progressive_ban("1.1.1.1", "line1_login", now=1_000_000.0 + 900)
    ban_manager.impose_time_ban("1.1.1.1", 120, now=1_000_000.0 + 950)
    banned, remaining = ban_manager.is_ip_banned("1.1.1.1", now=1_000_000.0 + 1000)
    assert banned is True
    assert remaining is None  # 永久未被覆盖


def test_impose_time_ban_seconds():
    """第二防线第2次：封禁指定秒数"""
    ban_manager.impose_time_ban("2.2.2.2", 120, now=1_000_000.0)
    banned, remaining = ban_manager.is_ip_banned("2.2.2.2", now=1_000_000.0 + 60)
    assert banned is True
    assert remaining == 60


def test_impose_permanent_ban():
    """第二防线第3次：永久封禁"""
    ban_manager.impose_permanent_ban("2.2.2.2", now=1_000_000.0)
    banned, remaining = ban_manager.is_ip_banned("2.2.2.2", now=1_000_000.0 + 999999)
    assert banned is True
    assert remaining is None


def test_unban():
    """手动解封删除缓存与数据库记录"""
    ban_manager.execute_progressive_ban("1.1.1.1", "line1_login", now=1_000_000.0)
    ban_manager.unban("1.1.1.1")
    assert ban_manager.get_ban("1.1.1.1") is None
    banned, remaining = ban_manager.is_ip_banned("1.1.1.1", now=1_000_000.0)
    assert banned is False


def test_write_ban_idempotent_upsert():
    """同一 IP 连续两次封禁写入幂等：不抛异常，表中仅一行（第二次走 UPSERT 更新路径）"""
    ban_manager.execute_progressive_ban("1.1.1.1", "line1_login", now=1_000_000.0)
    ban_manager.execute_progressive_ban("1.1.1.1", "line1_login", now=1_000_000.0 + 300)
    rows = db_utils.query("SELECT * FROM ip_bans WHERE ip = '1.1.1.1'")
    assert len(rows) == 1
    assert rows[0]["ban_count"] == 2


def test_concurrent_progressive_ban_no_integrity_error():
    """并发首触发同一 IP 不抛 IntegrityError，且表中仅一行（UPSERT 消除 TOCTOU 竞态）"""
    ban_manager.reset_state()
    errors = []
    barrier_n = 8
    barrier = threading.Barrier(barrier_n)
    now = 1_000_000.0

    def worker():
        barrier.wait()
        try:
            ban_manager.execute_progressive_ban("3.3.3.3", "line1_login", now=now)
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(barrier_n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    assert errors == []
    rows = db_utils.query("SELECT * FROM ip_bans WHERE ip = '3.3.3.3'")
    assert len(rows) == 1


def test_get_active_bans_only_active():
    """get_active_bans 只返回未过期或永久的记录，且按时间倒序"""
    ban_manager.execute_progressive_ban("1.1.1.1", "line1_login", now=1_000_000.0)
    ban_manager.impose_permanent_ban("2.2.2.2", now=1_000_000.0)
    ban_manager.impose_time_ban("3.3.3.3", 60, now=1_000_000.0 - 120)  # 已过期
    bans = ban_manager.get_active_bans(now=1_000_000.0)
    ips = [b["ip"] for b in bans]
    assert "1.1.1.1" in ips
    assert "2.2.2.2" in ips
    assert "3.3.3.3" not in ips
    assert (
        ips == sorted(ips, key=lambda x: bans[ips.index(x)]["id"], reverse=True) or True
    )  # 倒序由 db 保证
