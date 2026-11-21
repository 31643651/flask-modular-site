"""
项目模块化程度量化审计（只读）。

用法：
    py -3.12 scripts/module_audit.py

输出：
1. 各模块规模（文件数 / 代码行）
2. 最大文件 top 10
3. 模块依赖矩阵（Module.<x> 引用）与反向依赖告警（common/core → 业务模块）
4. 模块级循环依赖（SCC）
5. 跨文件重复代码块（6 行窗口、去空白）top 20
6. 模板内联 <script>/<style> 占比 top 10
7. 测试文件与模块覆盖粗查

Windows 中文环境请设置 PYTHONIOENCODING=utf-8。
"""

import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "Module"
BUSINESS_MODULES = [
    p.name
    for p in MODULE.iterdir()
    if p.is_dir() and p.name not in {"common", "core", "templates", "static", "data", "json", "log"}
]
INTERNAL_LAYERS = {"common", "core"}

IMPORT_RE = re.compile(r"^\s*(?:from|import)\s+Module\.(\w+)", re.MULTILINE)


def iter_py():
    yield ROOT / "app.py"
    yield ROOT / "session.py"
    for p in sorted(MODULE.rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        yield p


def iter_html():
    for p in sorted(MODULE.rglob("*.html")):
        yield p


def module_of(path):
    """返回文件所属模块名（app.py/session.py → <root>）"""
    try:
        rel = path.relative_to(MODULE)
        return rel.parts[0] if len(rel.parts) > 1 else "<root>"
    except ValueError:
        return "<root>"


def section(title):
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def main():
    py_files = list(iter_py())
    line_counts = {}
    module_files = defaultdict(list)
    module_lines = defaultdict(int)
    for p in py_files:
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        n = text.count("\n") + 1
        line_counts[p] = n
        m = module_of(p)
        module_files[m].append(p)
        module_lines[m] += n

    section("1. 各模块规模（Python）")
    print(f"{'模块':16s} {'文件数':>5s} {'代码行':>8s}")
    for m in sorted(module_lines, key=lambda k: -module_lines[k]):
        print(f"{m:16s} {len(module_files[m]):>5d} {module_lines[m]:>8d}")
    total = sum(module_lines.values())
    print(f"{'合计':16s} {len(py_files):>5d} {total:>8d}")

    section("2. 最大 Python 文件 top 10")
    for p, n in sorted(line_counts.items(), key=lambda kv: -kv[1])[:10]:
        print(f"{n:>6d}  {p.relative_to(ROOT)}")

    # 依赖矩阵
    section("3. 模块依赖矩阵与反向依赖")
    deps = defaultdict(set)  # 源模块 -> 目标模块集合
    for p in py_files:
        src = module_of(p)
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for target in IMPORT_RE.findall(text):
            if target in {"common", "core"} or target in BUSINESS_MODULES:
                if target != src:
                    deps[src].add(target)

    names = sorted(set(deps) | {t for s in deps.values() for t in s})
    print(f"{'源\\目标':14s}" + "".join(f"{n[:10]:>12s}" for n in names))
    for s in names:
        print(f"{s:14s}" + "".join(f"{'X' if t in deps[s] else '·':>12s}" for t in names))

    print("\n反向依赖告警（common/core 引用业务模块）：")
    reverse = []
    for layer in INTERNAL_LAYERS:
        for target in sorted(deps.get(layer, ())):
            if target not in {"common", "core"}:
                reverse.append((layer, target))
                print(f"  - Module/{layer} -> Module/{target}")
    if not reverse:
        print("  （无）")

    print("\n业务模块之间直接互引：")
    cross = []
    for s in BUSINESS_MODULES:
        for t in sorted(deps.get(s, ())):
            if t in BUSINESS_MODULES:
                cross.append((s, t))
                print(f"  - Module/{s} -> Module/{t}")
    if not cross:
        print("  （无）")

    # 循环依赖（模块级 SCC，Tarjan 简化：找互相可达对）
    section("4. 模块级循环依赖")
    graph = {m: set(deps.get(m, ())) & set(names) for m in names}

    def reachable(start):
        seen, stack = set(), [start]
        while stack:
            cur = stack.pop()
            for nxt in graph.get(cur, ()):
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        return seen

    cycles = set()
    for a in names:
        reach_a = reachable(a)
        for b in graph.get(a, ()):
            if a in reachable(b):
                cycles.add(tuple(sorted((a, b))))
    if cycles:
        for a, b in sorted(cycles):
            print(f"  - {a} <-> {b}")
    else:
        print("  （无模块级循环依赖）")

    # 重复代码块
    section("5. 跨文件重复代码块 top 20（6 行窗口，去空白）")
    WINDOW = 6
    windows = defaultdict(set)  # hash -> {文件}
    samples = {}
    for p in py_files + list(iter_html()):
        try:
            lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        norm = [re.sub(r"\s+", "", ln) for ln in lines]
        for i in range(len(norm) - WINDOW + 1):
            chunk = norm[i : i + WINDOW]
            if sum(len(c) for c in chunk) < 40:
                continue
            if all(c in {"", "}", "});", "};", "})", "</div>", "<div>", "});"} for c in chunk):
                continue
            key = "\n".join(chunk)
            windows[key].add(str(p.relative_to(ROOT)))
            samples.setdefault(key, (p, i + 1))
    duplicated = [(k, v) for k, v in windows.items() if len(v) >= 2]
    duplicated.sort(key=lambda kv: -len(kv[1]))
    for key, files in duplicated[:20]:
        p, lineno = samples[key]
        print(f"  [{len(files)} 个文件] 样例 {p.relative_to(ROOT)}:{lineno}  →  {sorted(files)[:4]}")
    print(f"  重复窗口总数: {len(duplicated)}")

    # 模板内联占比
    section("6. 模板内联 <script>/<style> 占比 top 10")
    rows = []
    for p in iter_html():
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        total_lines = text.count("\n") + 1
        inline = 0
        for tag in ("script", "style"):
            for m in re.finditer(rf"<{tag}[^>]*>(.*?)</{tag}>", text, re.DOTALL | re.IGNORECASE):
                inline += m.group(1).count("\n")
        rows.append((inline / max(total_lines, 1), total_lines, inline, p))
    for ratio, total, inline, p in sorted(rows, key=lambda r: -r[0])[:10]:
        print(f"  {ratio*100:5.1f}%  inline={inline:4d}/{total:4d}  {p.relative_to(ROOT)}")

    # 测试覆盖粗查
    section("7. 测试文件与模块覆盖粗查")
    tests = sorted((ROOT / "tests").glob("*.py"))
    print(f"测试文件数: {len(tests)}")
    named = Counter()
    for t in tests:
        name = t.stem
        for m in BUSINESS_MODULES + list(INTERNAL_LAYERS):
            if m in name or m.replace("_", "") in name.replace("_", ""):
                named[m] += 1
    for m in sorted(BUSINESS_MODULES + list(INTERNAL_LAYERS)):
        print(f"  {m:16s} 名称相关测试: {named.get(m, 0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
