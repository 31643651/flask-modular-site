"""
ipguard 蓝图：提供测试页与提示页的白名单路由
"""

from flask import Blueprint, render_template

ipguard_bp = Blueprint(
    "ipguard", __name__, url_prefix="/ipguard", template_folder="templates"
)


@ipguard_bp.route("/banned")
def banned_page():
    """展示被封禁提示页（供人工预览）"""
    return render_template(
        "ipguard/banned.html",
        reason_label="示例",
        remaining=300,
        permanent=False,
    )


@ipguard_bp.route("/rate_limited")
def rate_limited_page():
    """展示限速提示页（供人工预览）"""
    return render_template("ipguard/rate_limited.html", wait_seconds=60)
