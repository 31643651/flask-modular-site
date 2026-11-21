"""画廊三蓝图共用守卫（ADR-0009 去重：原先三份逐字相同的 before_request）"""


def check_gallery_enabled():
    """检查画廊功能是否启用；关闭时重定向首页"""
    from flask import redirect, url_for
    from Module.common.settings_utils import is_feature_enabled

    if not is_feature_enabled("gallery_enabled"):
        return redirect(url_for("index.index"))
