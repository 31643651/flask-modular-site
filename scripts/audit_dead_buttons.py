"""
全站死按钮审计脚本（ADR-0006 根因 A 配套审计）

扫描 Module/ 下所有 HTML 模板：
1. onclick 内联引用的 JS 函数必须在同模板内定义（否则点击无反应）；
2. confirmDialog 函数体必须先捕获 dialogCallback 再调用 closeDialog
   （否则确认框"确定"永不执行，ADR-0006 根因 A）。

用法：py -3.12 scripts/audit_dead_buttons.py
退出码：0=通过，1=发现问题
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "Module"


def extract_confirm_body(src: str) -> str:
    m = re.search(r"function confirmDialog\(\)\s*\{([\s\S]*?)\n\s*\}", src)
    return m.group(1) if m else ""


def main() -> int:
    problems = []
    templates = sorted(ROOT.rglob("*.html"))
    for p in templates:
        src = p.read_text(encoding="utf-8", errors="replace")

        # 1) onclick 引用的函数是否定义
        calls = set(re.findall(r"onclick\s*=\s*\"([A-Za-z_$][\w$]*)\s*\(", src))
        calls |= set(re.findall(r"onclick\s*=\s*'([A-Za-z_$][\w$]*)\s*\(", src))
        for fn in sorted(calls):
            if fn == "return":
                continue
            defined = (
                f"function {fn}(" in src
                or re.search(rf"(?:const|let|var)\s+{fn}\s*=", src)
                or re.search(rf"^\s*{fn}\s*=", src, re.M)
            )
            if not defined:
                problems.append(f"{p}: onclick 引用未定义函数 {fn}()")

        # 2) confirmDialog 时序
        if "function confirmDialog(" in src:
            body = extract_confirm_body(src)
            if body:
                read_pos = body.find("dialogCallback")
                close_pos = body.find("closeDialog")
                if read_pos == -1 or close_pos == -1 or read_pos > close_pos:
                    problems.append(
                        f"{p}: confirmDialog 未先捕获 dialogCallback 就调用 "
                        "closeDialog（确认动作永不执行）"
                    )

    if problems:
        print(f"发现 {len(problems)} 个问题：")
        for line in problems:
            print("  -", line)
        return 1
    print(f"审计通过：{len(templates)} 个模板，无死按钮/确认框时序问题")
    return 0


if __name__ == "__main__":
    sys.exit(main())
