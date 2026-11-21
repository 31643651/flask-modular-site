"""
ipguard 中间件

注册到 app.before_request，执行两级访问频率限制。
核心逻辑提取为独立函数便于单元测试；init_ipguard_middleware 包装为 Flask 中间件。
"""

import logging

from flask import render_template, request, session, make_response

from Module.common.user_utils import parse_user_agent, is_superadmin, get_user
from Module.common.web_paths import IPGUARD_WHITELIST_PREFIXES as WHITELIST_PREFIXES
from Module.common.net_utils import get_client_ip as _resolve_client_ip
from . import rate_limiter, ban_manager

logger = logging.getLogger(__name__)


def get_client_ip():
    """客户端真实 IP（委托 common.net_utils，保留模块级函数名供内部/测试调用）"""
    return _resolve_client_ip(request)


def is_whitelisted(path):
    """路径是否属于白名单"""
    for prefix in WHITELIST_PREFIXES:
        if path.startswith(prefix):
            return True
    return False


def is_other_ua():
    """UA 浏览器或 OS 为 Other（未知）"""
    parsed = parse_user_agent(request.user_agent.string or "")
    return parsed["browser"] == "未知浏览器" or parsed["os"] == "未知操作系统"


def _is_logged_in():
    return "user_id" in session


def _is_superadmin_request():
    """当前登录用户是否超级管理员"""
    if not _is_logged_in():
        return False
    user = get_user(session.get("username"))
    return bool(user and is_superadmin(user))


def _render_banned(ban):
    permanent = bool(ban.get("is_permanent"))
    reason_label = ban.get("ban_reason_label") or ban.get("ban_reason") or "访问受限"
    remaining = ban.get("remaining_seconds")
    return make_response(
        render_template(
            "ipguard/banned.html",
            reason_label=reason_label,
            remaining=remaining,
            permanent=permanent,
        ),
        429,
    )


def _render_rate_limited(wait_seconds=60):
    return make_response(
        render_template("ipguard/rate_limited.html", wait_seconds=wait_seconds),
        429,
    )


def _handle_request():
    """核心检查逻辑：返回 Response 表示拦截，返回 None 放行"""
    path = request.path

    # 1. 白名单放行
    if is_whitelisted(path):
        return None

    # 2. 超级管理员豁免（需要真实 IP 判定前先取 IP）
    is_super = _is_superadmin_request()
    if is_super:
        return None

    ip = get_client_ip()
    if not ip:
        return None

    # 3. 封禁检查
    banned, remaining = ban_manager.is_ip_banned(ip)
    if banned:
        ban = ban_manager.get_ban(ip) or {}
        ban["remaining_seconds"] = remaining
        return _render_banned(ban)

    # 4. 第二防线限速检查（1 分钟限速期内，除静态外拦截）
    if rate_limiter.in_line2_rate_limit(ip) and not path.startswith("/static/"):
        return _render_rate_limited()

    # 5. 第一防线：未登录访问 /user/login
    if not _is_logged_in() and path == "/user/login":
        rate_limiter.record_access(ip, bucket="login")
        if rate_limiter.exceed_limits(ip, "login"):
            ban = ban_manager.execute_progressive_ban(ip, "line1_login")
            return _render_banned(ban)

    # 6. 第一防线：UA 为 Other（所有非白名单页面）
    if is_other_ua():
        rate_limiter.record_access(ip, bucket="ua")
        if rate_limiter.exceed_limits(ip, "ua"):
            ban = ban_manager.execute_progressive_ban(ip, "line1_illegal_ua")
            return _render_banned(ban)

    # 7. 第二防线：非超级管理员 + GET + 非静态
    if _is_logged_in() and request.method == "GET" and not path.startswith("/static/"):
        if rate_limiter.record_path_access(ip, path):
            action = rate_limiter.handle_line2_trigger(ip)
            if action == "rate_limited":
                return _render_rate_limited()
            if action == "ban_2min":
                ban = ban_manager.impose_time_ban(ip, 120)
                return _render_banned(ban)
            if action == "permanent":
                ban_manager.impose_permanent_ban(ip)
                _disable_user_account(session.get("username"))
                ban = ban_manager.get_ban(ip) or {}
                return _render_banned(ban)

    return None


def _disable_user_account(username):
    """第二防线第3次触发：禁用用户账户"""
    if not username:
        return
    from Module.common import user_utils

    users = user_utils.load_users()
    if username not in users:
        return
    users[username]["enabled"] = False
    user_utils.save_users(users)


def init_ipguard_middleware(app):
    """注册 ipguard 检查中间件到 Flask 应用"""

    @app.before_request
    def ipguard_check():
        try:
            return _handle_request()
        except Exception:
            logger.exception("ipguard middleware error, allow request")
            return None  # 中间件异常放行，避免拖垮正常服务
