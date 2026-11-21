"""
重置本地开发库 admin 账号密码（带外恢复用，仅限本地 dev 库）。

用法：
    py -3.12 scripts/reset_admin_password.py <新密码>

作用：
    把 users 表中 username='admin' 的 password 哈希替换为新密码的
    werkzeug 哈希；admin 不存在时直接提示并退出（不做任何写入）。

保留入库原因：浏览器回归/验收时若 session 失效且无已知凭据，
需要一条可审计的恢复路径，而不是临时一行命令。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from werkzeug.security import generate_password_hash

from Module.common import db_utils


def main() -> int:
    if len(sys.argv) != 2 or not sys.argv[1]:
        print("用法: py -3.12 scripts/reset_admin_password.py <新密码>")
        return 2

    new_password = sys.argv[1]
    rows = db_utils.query("SELECT id FROM users WHERE username = 'admin'")
    if not rows:
        print("users 表中不存在 username='admin'，未做任何修改")
        return 1

    db_utils.execute(
        "UPDATE users SET password = ? WHERE username = 'admin'",
        (generate_password_hash(new_password),),
    )
    print(f"admin（id={rows[0]['id']}）密码已重置")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
