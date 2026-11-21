"""
用户控制模块

本模块负责用户认证、登录、动态密钥验证等功能。
所有数据通过 JSON 文件存储，符合模块化规范。
"""

import random
import string
import time
import threading
import logging
from secrets import token_urlsafe
from flask import (
    Blueprint,
    render_template,
    request,
    session,
    redirect,
    url_for,
    jsonify,
    make_response,
)

import secrets

# 获取日志记录器（使用根 logger 确保输出）
logger = logging.getLogger()

# 创建蓝图对象
user_bp = Blueprint("user", __name__, url_prefix="/user", template_folder="templates")


# ============================================================================
# 功能函数
# ============================================================================
# 从 common 模块导入共享函数
from Module.common.user_utils import load_users, get_user, add_activity, verify_user, is_superadmin
from Module.common.auth_utils import require_auth  # 供包级导出使用
from Module.common.security import generate_csrf_token, validate_csrf_token
from Module.core.user_service import UserService

_user_service = UserService()


def check_csrf():
    """
    校验请求是否携带正确的 CSRF 令牌

    Returns:
        bool: 令牌正确返回 True，否则 False
    """
    return validate_csrf_token()


def generate_verify_code():
    """
    生成16位大写验证码

    Returns:
        str: 16位大写字母验证码
    """
    return "".join(random.choices(string.ascii_uppercase, k=16))


def log_verify_code(code):
    """
    在日志中输出验证码

    Args:
        code: 验证码
    """
    logger.info(f"{'=' * 50}")
    logger.info(f"管理员动态验证码: {code}")
    logger.info(f"{'=' * 50}")


# ============================================================================
# 路由
# ============================================================================
@user_bp.route("", methods=["GET"])
@user_bp.route("/")
@user_bp.route("/profile")
def profile():
    """
    用户信息页面

    Returns:
        str: 渲染后的用户信息页面
    """
    # 检查用户是否登录
    if "user_id" not in session:
        return redirect(url_for("user.login"))

    user = get_user(session.get("username"))
    if not user or not user["enabled"]:
        session.clear()
        return redirect(url_for("user.login"))

    csrf_token = generate_csrf_token()
    return render_template("user/profile.html", user=user, csrf_token=csrf_token)


@user_bp.route("/login", methods=["GET", "POST"])
def login():
    """
    用户登录

    Returns:
        str: 渲染后的登录页面
    """
    # 已登录用户直接返回主页
    if "user_id" in session:
        user = get_user(session.get("username"))
        if user and user["enabled"]:
            # 管理员需要验证（检查设置开关）
            if is_superadmin(user) and not session.get("verified", False):
                from Module.common.settings_utils import is_feature_enabled

                if is_feature_enabled("admin_verify_enabled"):
                    return redirect(url_for("user.verify"))
                else:
                    session["verified"] = True
            return redirect(url_for("index.index"))

    if request.method == "POST":
        # CSRF 校验
        if not check_csrf():
            return (
                render_template(
                    "user/login.html",
                    error="请求已过期，请刷新页面重试",
                    csrf_token=generate_csrf_token(),
                ),
                400,
            )

        username = request.form.get("username")
        password = request.form.get("password")
        client_ip = request.remote_addr or "unknown"

        user = verify_user(username, password)
        if user:
            # 登录成功：清空该 IP 的失败计数
            _user_service.record_login_attempt(client_ip, failed=False)
            # 先清除旧会话，重新生成session ID
            # CSRF token 在下方登录成功后重新生成并写入 session+cookie，无需保留旧值
            session.clear()
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["role"] = user["role"]
            session["verified"] = False
            session.permanent = True  # 会话持久化，浏览器关闭后 cookie 不失

            # 记录用户登录活动
            add_activity(user["username"], "用户登录", request.remote_addr)

            # 管理员需要动态验证（检查设置开关）
            if is_superadmin(user):
                from Module.common.settings_utils import is_feature_enabled

                if is_feature_enabled("admin_verify_enabled"):
                    session["verified"] = False
                    response = make_response(redirect(url_for("user.verify")))
                else:
                    session["verified"] = True
                    response = make_response(redirect(url_for("index.index")))
            else:
                response = make_response(redirect(url_for("index.index")))

            # 设置 CSRF token cookie（非httponly，允许JS读取用于API请求）
            csrf_token = secrets.token_hex(32)
            session["csrf_token"] = csrf_token
            response.set_cookie(
                "csrf_token", csrf_token, httponly=False, samesite="Strict"
            )
            return response
        else:
            # 登录失败：累计失败计数，达到上限则拒绝，防止暴力破解
            if not _user_service.record_login_attempt(client_ip, failed=True):
                logger.warning(f"登录尝试次数过多: {client_ip}")
                return render_template(
                    "user/login.html",
                    error="登录尝试次数过多，请稍后再试",
                    csrf_token=generate_csrf_token(),
                )
            logger.warning(f"登录失败: {client_ip}, username: {username}")
            return render_template(
                "user/login.html",
                error="用户名或密码错误，或账户未启用",
                csrf_token=generate_csrf_token(),
            )

    # 生成 CSRF 令牌供表单使用
    csrf_token = generate_csrf_token()
    return render_template("user/login.html", csrf_token=csrf_token)


@user_bp.route("/verify", methods=["GET", "POST"])
def verify():
    """
    管理员动态密钥验证

    Returns:
        str: 渲染后的验证页面
    """
    # 检查是否已登录管理员（ADR-0004：角色判定以 DB 为单一权威源，
    # 不再读取登录时写入且永不失效的 session["role"]，消除 login↔verify 二元环）
    user = get_user(session.get("username")) if "user_id" in session else None
    if not user or not user["enabled"] or not is_superadmin(user):
        return redirect(url_for("user.login"))

    # 已验证则跳转到首页
    if session.get("verified", False):
        return redirect(url_for("index.index"))

    if request.method == "POST":
        # CSRF 校验
        if not check_csrf():
            return (
                render_template(
                    "user/verify.html",
                    error="请求已过期，请刷新页面重试",
                    csrf_token=generate_csrf_token(),
                ),
                400,
            )
        code = request.form.get("code", "").upper()

        # 验证码存储在 session 中
        if code == session.get("verify_code"):
            session["verified"] = True

            # 记录管理员验证活动
            add_activity(session.get("username"), "管理员验证通过", request.remote_addr)

            return redirect(url_for("index.index"))
        else:
            return render_template(
                "user/verify.html",
                error="验证码错误",
                csrf_token=generate_csrf_token(),
            )

    # 生成验证码并输出到日志
    verify_code = generate_verify_code()
    session["verify_code"] = verify_code
    log_verify_code(verify_code)

    csrf_token = generate_csrf_token()
    return render_template("user/verify.html", csrf_token=csrf_token)


@user_bp.route("/logout", methods=["POST"])
def logout():
    """
    用户退出登录

    Returns:
        redirect: 重定向到登录页
    """
    # CSRF 校验，防止跨站请求登出
    if not check_csrf():
        return (
            render_template(
                "user/login.html",
                error="请求已过期，请刷新页面重试",
                csrf_token=generate_csrf_token(),
            ),
            400,
        )

    # 记录用户登出活动
    add_activity(session.get("username"), "用户退出登录", request.remote_addr)

    session.clear()
    return redirect(url_for("user.login"))
