"""
确认框回调时序 + 公共 UI 脚本引用测试（ADR-0006 根因 A）

背景：8 个模板的 confirmDialog() 曾先调 closeDialog()（把 dialogCallback 置
null），随后才判断 if (dialogCallback)，导致回调永远不触发——全站所有
showConfirm 确认框点"确定"都不执行后续动作（日志清理断链、挂载删除失效、
死按钮的共同根因）。

修复后上述重复实现已收敛到 Module/static/common/ui.js。本测试锚定：
1. ui.js 的 confirmDialog 函数体内先读取 dialogCallback（保存到局部变量），
   再调用 closeDialog()，并用捕获的局部变量触发回调；
2. 8 个原模板均引用 /static/common/ui.js；
3. 模板不再各自重复定义 confirmDialog（防止多份实现再次分叉）。
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
UI_JS = ROOT / "Module/static/common/ui.js"

TEMPLATES = [
    ROOT / "Module/admin/templates/admin/activity.html",
    ROOT / "Module/admin/templates/admin/activity_all.html",
    ROOT / "Module/admin/templates/admin/config.html",
    ROOT / "Module/admin/templates/admin/users.html",
    ROOT / "Module/admin/templates/admin/userfix.html",
    ROOT / "Module/admin/templates/admin/dashboard.html",
    ROOT / "Module/gallery/templates/gallery/favorites.html",
    ROOT / "Module/index/templates/index/index.html",
]


def _function_body(source: str, name: str) -> str:
    """提取无参函数体（函数体无嵌套大括号，单层正则即可）。"""
    m = re.search(rf"function {name}\(\)\s*\{{([\s\S]*?)\n\s*\}}", source)
    assert m, f"缺少 {name} 函数定义"
    return m.group(1)


def test_ui_js_exists():
    assert UI_JS.is_file(), f"缺少公共 UI 脚本: {UI_JS}"


def test_confirm_reads_callback_before_close():
    """confirmDialog 必须在 closeDialog 之前捕获 dialogCallback。

    旧实现 closeDialog() 在前（置空回调），随后判断回调 → 永不执行；
    修复后先 `var cb = dialogCallback;` 再 closeDialog() 再触发 cb。
    """
    body = _function_body(UI_JS.read_text(encoding="utf-8"), "confirmDialog")
    read_pos = body.find("dialogCallback")
    close_pos = body.find("closeDialog")
    assert read_pos != -1, "confirmDialog 未读取 dialogCallback"
    assert close_pos != -1, "confirmDialog 未调用 closeDialog"
    assert read_pos < close_pos, (
        "confirmDialog 必须先捕获 dialogCallback 再调用 closeDialog，"
        "否则回调被置空、确认动作永不执行（ADR-0006 根因 A）"
    )


def test_confirm_triggers_captured_callback():
    """修复后用局部变量触发回调（而非已被置空的 dialogCallback）。"""
    body = _function_body(UI_JS.read_text(encoding="utf-8"), "confirmDialog")
    assert "cb(" in body or "callback(" in body, (
        "confirmDialog 必须用捕获的局部变量触发回调"
    )


@pytest.mark.parametrize("template", TEMPLATES, ids=lambda p: p.name)
def test_template_exists(template):
    assert template.is_file(), f"模板不存在: {template}"


@pytest.mark.parametrize("template", TEMPLATES, ids=lambda p: p.name)
def test_template_includes_common_ui_script(template):
    source = template.read_text(encoding="utf-8")
    assert "/static/common/ui.js" in source, (
        f"{template.name} 未引用公共脚本 /static/common/ui.js"
    )


@pytest.mark.parametrize("template", TEMPLATES, ids=lambda p: p.name)
def test_template_does_not_redefine_confirm_dialog(template):
    """确认框实现只允许存在于 ui.js，模板内不得再次定义。"""
    source = template.read_text(encoding="utf-8")
    assert not re.search(r"function\s+confirmDialog\s*\(", source), (
        f"{template.name} 仍在重复定义 confirmDialog，应改用 ui.js"
    )
