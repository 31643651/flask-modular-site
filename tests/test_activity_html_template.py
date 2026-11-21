"""
activity.html 模板完整性测试

背景：该文件曾在 cleanupLogs 函数结尾处被截断，缺少两个 </script> 与
</body></html> 闭合标签，导致浏览器 JS SyntaxError、页面功能全部失效
（bug #3，高危）。本测试防止回归。
"""

from pathlib import Path

import pytest
from jinja2 import Environment

TEMPLATE_PATH = (
    Path(__file__).resolve().parent.parent
    / "Module" / "admin" / "templates" / "admin" / "activity.html"
)
UI_JS_PATH = (
    Path(__file__).resolve().parent.parent
    / "Module" / "static" / "common" / "ui.js"
)


@pytest.fixture(scope="module")
def template_source() -> str:
    return TEMPLATE_PATH.read_text(encoding="utf-8")


def test_template_exists():
    assert TEMPLATE_PATH.is_file(), f"模板文件不存在: {TEMPLATE_PATH}"


def test_jinja_parse(template_source):
    """模板必须可通过 Jinja 语法解析。"""
    Environment().parse(template_source)


def test_script_tags_paired(template_source):
    """<script> 与 </script> 数量必须一致（截断回归的直接信号）。"""
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
    """HTML 中 onclick 引用的 JS 函数必须可用。

    模板自有函数仍须在模板内定义；对话框函数已收敛到公共 ui.js，
    通过外链脚本提供，模板不再重复定义。
    """
    for fn in (
        "filterActivities",
        "toggleGroup",
        "toggleCleanupMenu",
        "cleanupLogs",
    ):
        assert f"function {fn}(" in template_source, f"缺少函数定义: {fn}"

    assert '<script src="/static/common/ui.js"></script>' in template_source, (
        "缺少公共 UI 脚本引用（对话框函数由 ui.js 提供）"
    )
    ui_source = UI_JS_PATH.read_text(encoding="utf-8")
    for fn in ("closeDialog", "confirmDialog"):
        assert f"function {fn}(" in ui_source, f"ui.js 缺少函数定义: {fn}"
        assert f"function {fn}(" not in template_source, (
            f"{fn} 应只存在于 ui.js，模板内不得重复定义"
        )


def test_xss_escape_preserved(template_source):
    """security-audit.md S7/S8：escapeHtml 转义逻辑必须存在，不得回退。"""
    assert "function escapeHtml(" in template_source
