"""
认证工具模块

提供用户认证检查等共享功能。
"""

from flask import request, session, redirect, url_for
from .user_utils import get_user, is_superadmin

# 白名单路径（不需要认证的路径；统一来自 common.web_paths）
from .web_paths import AUTH_WHITELIST as WHITELIST


def check_auth():
    """
    检查用户认证状态

    Returns:
        bool: True 表示已认证，False 表示未认证
    """
    # 检查是否在白名单中（URL 路径恒为正斜杠，直接比较防止遍历）
    path = request.path
    for whitelist_path in WHITELIST:
        if path == whitelist_path or path.startswith(whitelist_path + "/"):
            return True

    # 检查用户是否登录
    if "user_id" not in session:
        return False

    # 检查用户是否有效
    user = get_user(session.get("username"))
    if not user or not user["enabled"]:
        return False

    # 检查超级管理员是否通过动态验证（ADR-0007：收窄到仅超管）
    if is_superadmin(user) and not session.get("verified", False):
        return False

    return True


def require_auth():
    """
    要求认证的装饰器

    Returns:
        redirect: 重定向到登录页或验证页
    """
    if not check_auth():
        if "user_id" in session:
            user = get_user(session.get("username"))
            if user and is_superadmin(user):
                return redirect(url_for("user.verify"))
        return redirect(url_for("user.login"))
    return None


def register_auth_middleware(app):
    """
    注册认证中间件到 Flask 应用（原 AdminService.register_auth_middleware，
    迁出服务层：中间件属 Web 基础设施，不属于任何业务服务）。
    """
    from .user_utils import add_activity as _add_activity
    from .net_utils import get_client_ip
    from flask import request, session

    EXCLUDED_PATHS = [
        "/static/",
        "/favicon.ico",
        "/admin/activity/api",
        "/admin/activity/",
        "/admin/activity",
        "/setup",
    ]

    @app.before_request
    def authentication_check():
        request_path = request.path
        should_exclude = False
        for excluded in EXCLUDED_PATHS:
            if request_path.startswith(excluded):
                should_exclude = True
                break
        if not should_exclude:
            username = session.get("username", "")
            is_logged_in = "user_id" in session
            if is_logged_in:
                description = f"访问页面：{request_path}"
            else:
                description = f"未登录访问：{request_path}"
            real_ip = get_client_ip(request)
            _add_activity(
                username=username,
                description=description,
                ip=real_ip,
                path=request_path,
                user_agent=request.user_agent.string,
                is_logged_in=is_logged_in,
            )
        return require_auth()
