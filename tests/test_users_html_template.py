"""
users.html 模板完整性测试

背景：该页面曾有第一个 <script> 块在顶层立即绑定
`registerForm` 的 submit 事件，而回调 `registerUser` 定义在
第二个 <script> 块中。JS 函数声明只在同一 script 块内提升，
跨块不提升 → ReferenceError，绑定失败，且异常中断了第一块
后续代码，`checkDarkMode()` 被跳过（该页暗夜模式不生效）
（bug #4，高危）。本测试防止回归。
"""

import re
from pathlib import Path

import pytest
from jinja2 import Environment

TEMPLATE_PATH = (
    Path(__file__).resolve().parent.parent
    / "Module" / "admin" / "templates" / "admin" / "users.html"
)
UI_JS_PATH = (
    Path(__file__).resolve().parent.parent
    / "Module" / "static" / "common" / "ui.js"
)

# 内联 script 块（排除外链 <script src=...>，其内容不在本文件内）
_SCRIPT_BLOCK_RE = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", re.DOTALL)
_FUNCTION_DEF_RE = re.compile(r"\bfunction\s+([A-Za-z_$][\w$]*)\s*\(")


@pytest.fixture(scope="module")
def template_source() -> str:
    return TEMPLATE_PATH.read_text(encoding="utf-8")


def test_template_exists():
    assert TEMPLATE_PATH.is_file(), f"模板文件不存在: {TEMPLATE_PATH}"


def test_jinja_parse(template_source):
    """模板必须可通过 Jinja 语法解析。"""
    Environment().parse(template_source)


def test_script_tags_paired(template_source):
    """<script> 与 </script> 数量必须一致。"""
    assert template_source.count("<script") == template_source.count("</script>") > 0


def test_document_structure_closed(template_source):
    """文档必须包含 html/body 的闭合标签，且闭合标签位于文件末尾。"""
    stripped = template_source.rstrip()
    assert stripped.endswith("</html>")
    assert "</body>" in stripped
    # 闭合顺序：最后三个非空行应为 </script>、</body>、</html>
    tail_lines = [line.strip() for line in stripped.splitlines()[-3:]]
    assert tail_lines == ["</script>", "</body>", "</html>"]


def test_referenced_functions_defined(template_source):
    """页面引用的 JS 函数必须可用。

    模板自有函数仍须在模板内定义；对话框与暗夜模式函数已收敛到
    公共 ui.js，通过外链脚本提供，模板不再重复定义。
    """
    for fn in (
        "filterUsers",
        "toggleUserStatus",
        "deleteUser",
        "registerUser",
    ):
        assert f"function {fn}(" in template_source, f"缺少函数定义: {fn}"

    assert '<script src="/static/common/ui.js"></script>' in template_source, (
        "缺少公共 UI 脚本引用（对话框/暗夜模式函数由 ui.js 提供）"
    )
    ui_source = UI_JS_PATH.read_text(encoding="utf-8")
    for fn in (
        "showDialog",
        "showAlert",
        "showConfirm",
        "closeDialog",
        "confirmDialog",
    ):
        assert f"function {fn}(" in ui_source, f"ui.js 缺少函数定义: {fn}"
        assert f"function {fn}(" not in template_source, (
            f"{fn} 应只存在于 ui.js，模板内不得重复定义"
        )
    assert "function applyDarkModeFromCookie(" in ui_source, (
        "ui.js 缺少暗夜模式引导函数"
    )
    assert "function checkDarkMode(" not in template_source, (
        "checkDarkMode 已由 ui.js 的 applyDarkModeFromCookie 统一接管"
    )


def test_register_form_submit_bound(template_source):
    """注册表单必须绑定 submit 监听（否则走默认提交导致整页刷新）。"""
    assert re.search(
        r"getElementById\('registerForm'\)\.addEventListener\('submit',\s*registerUser\)",
        template_source,
    )


def test_dark_mode_checked_on_load(template_source):
    """页面加载时必须应用暗夜模式（曾因绑定异常被跳过）。

    现由公共 ui.js 在 DOMContentLoaded 时统一执行，模板须引用该脚本。
    """
    assert '<script src="/static/common/ui.js"></script>' in template_source, (
        "缺少 ui.js 引用，暗夜模式不会在加载时应用"
    )
    ui_source = UI_JS_PATH.read_text(encoding="utf-8")
    assert re.search(
        r"document\.addEventListener\('DOMContentLoaded',\s*applyDarkModeFromCookie\)",
        ui_source,
    ), "ui.js 未在 DOMContentLoaded 时应用暗夜模式"


def _strip_strings_and_comments(js: str):
    """去掉字符串/模板字面量内容与注释，保留代码字符，并返回
    (代码文本, 与文本逐字符对齐的花括号深度列表)。

    支持 '...'、"..."、`...`（含 ${...} 插值）、// 与 //**/ 注释。
    """
    out = []
    depths = []
    depth = 0
    tpl_stack = []  # 每项为进入 ${ 插值前的 depth
    state = "code"
    i, n = 0, len(js)
    while i < n:
        c = js[i]
        nxt = js[i + 1] if i + 1 < n else ""
        if state == "code":
            if c == "/" and nxt == "/":
                state = "line"
                i += 2
                continue
            if c == "/" and nxt == "*":
                state = "block"
                i += 2
                continue
            if c == "'":
                state = "sq"
                i += 1
                continue
            if c == '"':
                state = "dq"
                i += 1
                continue
            if c == "`":
                state = "tpl"
                i += 1
                continue
            if c == "{":
                depth += 1
            elif c == "}":
                if tpl_stack and depth - 1 == tpl_stack[-1]:
                    tpl_stack.pop()
                    depth -= 1
                    state = "tpl"
                    i += 1
                    continue
                depth -= 1
            out.append(c)
            depths.append(depth)
            i += 1
            continue
        if state == "line":
            if c == "\n":
                state = "code"
                out.append("\n")
                depths.append(depth)
            i += 1
            continue
        if state == "block":
            if c == "*" and nxt == "/":
                state = "code"
                i += 2
            else:
                i += 1
            continue
        if state in ("sq", "dq"):
            if c == "\\":
                i += 2
                continue
            if c in ("'", '"') or c == "\n":
                state = "code"
            i += 1
            continue
        # state == "tpl"：丢弃模板字面量文本，仅 ${...} 插值保留为代码
        if c == "\\":
            i += 2
            continue
        if c == "`":
            state = "code"
            i += 1
            continue
        if c == "$" and nxt == "{":
            tpl_stack.append(depth)
            depth += 1
            state = "code"
            i += 2
            continue
        i += 1
    return "".join(out), depths


def _top_level_identifiers(js: str):
    """返回 script 块中位于花括号深度 0（顶层立即执行代码）的标识符集合。

    排除紧跟在 `.` 之后的属性访问名。
    """
    code, depths = _strip_strings_and_comments(js)
    ids = set()
    for m in re.finditer(r"[A-Za-z_$][\w$]*", code):
        start = m.start()
        if start > 0 and code[start - 1] == ".":
            continue
        if depths[start] == 0:
            ids.add(m.group())
    return ids


def test_no_cross_block_top_level_references(template_source):
    """任何 script 块顶层立即执行的代码，不得引用仅在后续块中定义的函数。

    JS 函数声明只在同一 script 块内提升，跨块不提升：若顶层代码引用
    后续块的函数会直接 ReferenceError 并中断本块剩余初始化逻辑。
    嵌套函数体内的引用属运行时回调，不受此限制，不计入。
    """
    blocks = _SCRIPT_BLOCK_RE.findall(template_source)
    assert len(blocks) >= 1, "未找到任何内联 script 块"
    per_block_defs = [
        set(_FUNCTION_DEF_RE.findall(b)) for b in blocks
    ]
    problems = []
    for idx, block in enumerate(blocks):
        later_defs = set().union(*per_block_defs[idx + 1:]) if idx + 1 < len(blocks) else set()
        earlier_or_same = set().union(*per_block_defs[: idx + 1])
        leaked = sorted(
            name for name in _top_level_identifiers(block)
            if name in later_defs and name not in earlier_or_same
        )
        if leaked:
            problems.append(f"第 {idx + 1} 个 script 块顶层引用了后续块定义的函数: {leaked}")
    assert not problems, "；".join(problems)
