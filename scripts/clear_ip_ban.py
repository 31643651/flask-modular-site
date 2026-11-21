"""
清除 ipguard 对某个 IP 的持久化封禁（开发环境工具）。

用法：
    py -3.12 scripts/clear_ip_ban.py [IP]     # 默认 127.0.0.1

说明：ipguard 的封禁同时存在于内存缓存与 SQLite ip_bans 表（重启不丢失）。
清库后需重启 dev 服务器以刷新内存缓存。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from Module.common import db_utils


def main():
    ip = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
    before = db_utils.query("SELECT * FROM ip_bans WHERE ip = ?", (ip,))
    db_utils.execute("DELETE FROM ip_bans WHERE ip = ?", (ip,))
    after = db_utils.query("SELECT * FROM ip_bans WHERE ip = ?", (ip,))
    print(f"[clear_ip_ban] {ip}: 清除 {len(before)} 条，剩余 {len(after)} 条")
    print("[clear_ip_ban] 请重启 dev 服务器以刷新内存封禁缓存")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
