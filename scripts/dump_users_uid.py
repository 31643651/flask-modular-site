"""
只读：打印当前 users 表 uid 分布，并按新区间归类，评估 uid 分区方案的迁移影响。
"""
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
db = Path("Module/data/app.db")

con = sqlite3.connect(str(db))
con.row_factory = sqlite3.Row
rows = con.execute(
    "SELECT id, username, role, enabled, is_superadmin FROM users ORDER BY id"
).fetchall()
con.close()

print("用户总数:", len(rows))
for r in rows:
    print(
        f"  id={r['id']:>5}  {r['username']:<20} "
        f"role={r['role']:<8} enabled={r['enabled']} is_superadmin={r['is_superadmin']}"
    )


def band(uid):
    if uid <= 9:
        return "0-9 (超管区)"
    if uid <= 99:
        return "10-99"
    if uid <= 1000:
        return "100-1000 (保留区)"
    return "1001+ (新建区)"


print()
c = Counter(band(r["id"]) for r in rows)
for k in sorted(c):
    print(f"  {k}: {c[k]}")

# 列出会受"100-1000 保留区禁止新建"影响的存量（落在保留区但 id 很大却不该被禁止？）
print()
print("落在 10-99 区间的存量（允许，但需确认可被手动建在该区）：")
for r in rows:
    if 10 <= r["id"] <= 99:
        print(f"  id={r['id']} {r['username']} role={r['role']}")
print("落在 100-1000 区间的存量（新规则下该区间仅保留、不允许手动建）：")
for r in rows:
    if 100 <= r["id"] <= 1000:
        print(f"  id={r['id']} {r['username']} role={r['role']}")
