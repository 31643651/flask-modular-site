"""
安全工具模块

提供 CSRF 保护、安全响应头等安全相关功能。
支持装饰器和全局中间件两种 CSRF 保护模式。
"""

import secrets
import time
from functools import wraps

import structlog
from flask import Response, request, session


# --- CSRF Token Functions ---


def generate_csrf_token():
    """
    生成或返回当前会话的 CSRF 令牌（会话内保持不变）

    Returns:
        str: CSRF 令牌
    """
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(32)
    return session["csrf_token"]


def validate_csrf_token():
    """
    验证请求中的 CSRF 令牌

    Returns:
        bool: 令牌有效返回 True
    """
    token = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token")
    expected = session.get("csrf_token")
    return bool(token) and bool(expected) and token == expected


# --- Decorator for CSRF Protection ---


def csrf_protect(f):
    """
    装饰器：对单个路由启用 CSRF 验证
    """

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if request.method in ("POST", "PUT", "DELETE", "PATCH"):
            if not validate_csrf_token():
                return {"code": 403, "data": None, "msg": "CSRF token无效或缺失"}, 403
        return f(*args, **kwargs)

    return decorated_function


# --- Global Middleware Hook ---


def init_csrf_middleware(app):
    """
    注册全局 CSRF 保护中间件

    Args:
        app: Flask 应用实例
    """
    from Module.common.web_paths import CSRF_EXEMPT_PATHS as EXEMPT_PATHS

    @app.before_request
    def check_csrf():
        if request.method in ("POST", "PUT", "DELETE", "PATCH"):
            if request.path in EXEMPT_PATHS:
                return None
            if not validate_csrf_token():
                return {"code": 403, "data": None, "msg": "CSRF验证失败"}, 403


# --- Security Headers ---

# ADR-0011：允许一年强缓存的版本化静态资源前缀（模板经 static_url 附加 ?v=mtime）
_IMMUTABLE_STATIC_PREFIXES = ("/static/gallery/css/", "/static/gallery/js/")


def apply_cache_policy(response):
    """
    ADR-0011：按资源类型设置 Cache-Control

    - HTML 页面 → no-store（动态内容不缓存）
    - /static/ 带 ?v= 版本号（画廊 CSS/JS）→ 一年 immutable
    - 其它 /static/ → 1 小时
    - 图片（image/*）→ 1 天
    - JSON / 其它 → 不设置（保持默认，避免 API 被缓存）
    """
    if request.method != "GET":
        return response
    path = request.path
    mimetype = response.mimetype or ""
    if mimetype == "text/html":
        response.headers["Cache-Control"] = "no-store"
        return response
    if path.startswith("/static/"):
        # 静态资源与 Cookie 无关：去掉 Flask 自动附加的 Vary: Cookie，
        # 否则浏览器对每个 Cookie 变体都重新协商，无法直接命中强缓存
        response.headers["Vary"] = "Accept-Encoding"
        if request.args.get("v") and path.startswith(_IMMUTABLE_STATIC_PREFIXES):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            response.headers["Cache-Control"] = "public, max-age=3600"
        return response
    if mimetype.startswith("image/"):
        # 图片同样与 Cookie 无关（登录态由页面路由把守），允许完整缓存
        response.headers["Vary"] = "Accept-Encoding"
        response.headers["Cache-Control"] = "public, max-age=86400"
        return response
    return response


def add_security_headers(response, production_mode=False):
    """
    添加安全响应头与缓存策略头

    Args:
        response: Flask 响应对象
        production_mode: 是否为生产模式（启用 HSTS）

    Returns:
        添加了安全头的响应对象
    """
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob:; "
        "font-src 'self'; "
        "connect-src 'self'; "
        "frame-ancestors 'self'"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    if production_mode:
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
    return apply_cache_policy(response)


# --- 302 重定向循环熔断（ADR-0004）---

REDIRECT_WINDOW_SECONDS = 2.0
REDIRECT_LIMIT = 4
REDIRECT_STATUS_CODES = (301, 302, 303, 307, 308)


def init_redirect_circuit_breaker(app):
    """
    注册 302 硬限制中间件：同一会话 2 秒窗口内累计第 REDIRECT_LIMIT(4) 个
    重定向响应立即熔断为 508 Loop Detected，不再下发 Location；
    非重定向响应清零窗口。作为服务端兜底，防任何未知成环路径。
    """
    logger = structlog.get_logger(__name__)

    @app.after_request
    def redirect_circuit_breaker(response):
        if response.status_code not in REDIRECT_STATUS_CODES:
            session.pop("_redirect_window", None)
            return response

        now = time.time()
        stamps = [
            t
            for t in session.get("_redirect_window", [])
            if now - t < REDIRECT_WINDOW_SECONDS
        ]
        stamps.append(now)
        if len(stamps) >= REDIRECT_LIMIT:
            session.pop("_redirect_window", None)
            logger.warning(
                "redirect_circuit_breaker_tripped",
                path=request.path,
                limit=REDIRECT_LIMIT,
                window_seconds=REDIRECT_WINDOW_SECONDS,
            )
            return Response(
                "检测到重定向循环，访问已终止（508 Loop Detected）",
                status=508,
                content_type="text/plain; charset=utf-8",
            )
        session["_redirect_window"] = stamps
        return response
