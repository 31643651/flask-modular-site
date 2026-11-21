"""
Flask应用主程序入口

本文件负责：
- 提供 create_app 工厂函数创建Flask应用实例
- 配置应用基础设置
- 注册所有功能模块的蓝图
- 支持测试注入临时数据库路径与配置

不包含任何业务逻辑路由，所有路由定义在各模块中。
工厂化后 import app 不再触发任何数据库/服务器副作用。
"""

from flask import Flask, request, jsonify, redirect, url_for, render_template

import os
import subprocess
import sys
import logging
import secrets
import time
from datetime import timedelta
from pathlib import Path

# 获取日志记录器
logger = logging.getLogger(__name__)


def create_app(config=None, db_path=None):
    """
    创建并配置 Flask 应用实例。

    原模块级创建逻辑已移入本工厂，便于测试注入临时数据库路径与配置，隔离真实数据。

    Args:
        config: 可选 dict，合并进应用配置（覆盖默认值）。
        db_path: 可选数据库文件路径；非 None 时调用 db_utils.set_db_path 切换
            到临时库，用于测试隔离。None 时保持默认 DB_FILE（现状行为）。

    Returns:
        Flask 应用实例。
    """
    # 检查是否启用生产模式（读取真实进程 argv）
    production_mode = "--production" in sys.argv

    # 创建 Flask 应用实例
    app = Flask(
        __name__, template_folder="Module/templates", static_folder="Module/static"
    )

    # 应用配置
    if production_mode:
        secret_key = os.environ.get("SECRET_KEY")
        if not secret_key:
            secret_key = secrets.token_hex(32)
        app.config["SECRET_KEY"] = secret_key
        logger.info("SECRET_KEY generated randomly for this session")
    else:
        app.config["SECRET_KEY"] = "dev-secret-key-change-in-production"
    # 登录会话持久时长：浏览器关闭后 cookie 仍有效，减轻"重启掉登录"体验问题
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=7)
    app.config["JSON_AS_ASCII"] = False  # 支持中文JSON输出

    # Session Cookie 安全属性
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    if production_mode:
        app.config["SESSION_COOKIE_SECURE"] = True

    # 合并调用方传入的配置（覆盖默认值，测试常用）
    if config:
        app.config.update(config)

    # 确保 Module 目录存在
    module_dir = os.path.join(os.path.dirname(__file__), "Module")
    if not os.path.exists(module_dir):
        os.makedirs(module_dir)

    # 暗夜模式配置
    @app.context_processor
    def inject_dark_mode():
        """注入暗夜模式状态到所有模板"""

        def get_dark_mode():
            return request.cookies.get("darkMode", "false") == "true"

        return {"dark_mode": get_dark_mode()}

    # 若提供 db_path，切换到临时数据库（测试隔离）
    # 注意：SD Inspector 已改为静态站挂载，不再注册蓝图
    from Module.common import db_utils

    if db_path is not None:
        db_utils.set_db_path(db_path)

    # 注册各模块蓝图
    # setup模块 - 必须在其他模块之前注册，用于初始配置
    from Module.setup import setup_bp

    app.register_blueprint(setup_bp)

    # ipguard模块 - 访问频率限制
    from Module.ipguard import ipguard_bp

    app.register_blueprint(ipguard_bp)

    from Module.index import index_bp

    app.register_blueprint(index_bp)

    # books模块
    from Module.books import books_bp

    app.register_blueprint(books_bp)

    # user模块
    from Module.user import user_bp

    app.register_blueprint(user_bp)

    # admin模块 - 拆分为多个蓝图
    from Module.admin import (
        admin_bp,
        admin_activity_bp,
        admin_users_bp,
        admin_config_bp,
        admin_mounted_bp,
        admin_setting_bp,
        admin_ip_bp,
    )

    app.register_blueprint(admin_bp)
    app.register_blueprint(admin_activity_bp)
    app.register_blueprint(admin_users_bp)
    app.register_blueprint(admin_config_bp)
    app.register_blueprint(admin_mounted_bp)
    app.register_blueprint(admin_setting_bp)
    app.register_blueprint(admin_ip_bp)

    # log模块（仅中间件；无路由蓝图）
    from Module.log import register_log_middleware

    # userfix模块 - 拆分为多个蓝图
    from Module.userfix import userfix_bp, userfix_admin_bp

    app.register_blueprint(userfix_bp)
    app.register_blueprint(userfix_admin_bp)

    # gallery模块 - 拆分为多个蓝图
    from Module.gallery import (
        gallery_bp,
        gallery_favorites_bp,
        gallery_preferences_bp,
    )

    app.register_blueprint(gallery_bp)
    app.register_blueprint(gallery_favorites_bp)
    app.register_blueprint(gallery_preferences_bp)

    # 检查初始配置中间件
    @app.before_request
    def check_initial_setup():
        """检查初始配置是否完成"""
        from Module.common.paths import CONFIG_FILE
        from flask import request, redirect, url_for

        # 如果访问的是 setup 页面，直接放行（精确匹配 /setup 或 /setup/ 前缀，
        # 防止 /setupfoo 类挂载路径被 startswith 误豁免——ADR-0004）
        if request.path == "/setup" or request.path.startswith("/setup/"):
            return None

        # 检查 config.json 是否存在
        if not CONFIG_FILE.exists():
            return redirect(url_for("setup.index"))

        return None

    # 初始化服务器信息（由AdminService负责）
    from Module.core.admin_service import AdminService

    admin_svc = AdminService()
    admin_svc.init_server_info()

    # 初始化 SQLite 数据库（建表并从 JSON 导入历史数据）
    from Module.common.db_utils import init_db

    init_db()

    # 启动期 admin 常驻兜底（ADR-0003）：仅非首次部署执行；
    # config 缺失时由 setup 向导在步骤 2 创建 admin，避免主键冲突
    from Module.common.paths import CONFIG_FILE

    if CONFIG_FILE.exists():
        from Module.common.user_utils import ensure_admin_exists

        ensure_admin_exists()

    # ipguard访问限制：加载封禁缓存并注册中间件
    from Module.ipguard.ban_manager import load_ban_cache
    from Module.ipguard.middleware import init_ipguard_middleware

    load_ban_cache()
    init_ipguard_middleware(app)

    # 注册认证中间件（Web 基础设施，已从 AdminService 迁出）
    from Module.common.auth_utils import register_auth_middleware

    register_auth_middleware(app)

    # 注册日志中间件
    # 调试模式下 Werkzeug 重载器会启动父子两个进程，若两者同时创建文件日志，
    # 父进程会一直占用 app.log，导致 Windows 下按天滚动重命名失败（WinError 32）。
    # 因此仅在重载器子进程（实际服务进程）或生产模式（单进程）下启用文件日志，
    # 重载器父进程只保留控制台日志。
    from werkzeug.serving import is_running_from_reloader

    register_log_middleware(
        app,
        enable_file_logging=(production_mode or is_running_from_reloader()),
    )

    # CSRF 保护中间件 + 302 重定向循环熔断（ADR-0004）
    from Module.common.security import (
        add_security_headers,
        init_csrf_middleware,
        init_redirect_circuit_breaker,
    )

    init_csrf_middleware(app)

    # 安全响应头中间件
    @app.after_request
    def apply_security_headers(response):
        return add_security_headers(response, production_mode=production_mode)

    # 302 硬限制兜底：2 秒窗口内第 4 个重定向 → 508 Loop Detected
    # （after_request 逆序执行：熔断先跑，安全响应头仍会补到 508 上）
    init_redirect_circuit_breaker(app)

    # 全局错误处理（ADR-0010：页面导航渲染统一错误页，API/fetch 保持 JSON）
    def _prefers_json_error():
        """错误响应是否返回 JSON（API/非导航请求）"""
        if request.is_json:
            return True
        if "/api/" in request.path or request.path.endswith("/api"):
            return True
        if request.method not in ("GET", "HEAD"):
            return True
        return not request.accept_mimetypes.accept_html

    def _render_error_page(status, title, desc):
        return render_template(
            "errors/error.html", status=status, title=title, desc=desc
        ), status

    @app.errorhandler(404)
    def not_found(error):
        """404错误处理（页面 → 错误页；API → JSON）"""
        if _prefers_json_error():
            return {"error": "Not found", "code": 404}, 404
        return _render_error_page(404, "页面不存在", "你访问的页面不存在或已被移走。")

    @app.errorhandler(403)
    def forbidden(error):
        """403错误处理（页面 → 错误页；API → JSON）"""
        if _prefers_json_error():
            return {"error": "Forbidden", "code": 403}, 403
        return _render_error_page(403, "访问被拒绝", "你没有权限访问该页面。")

    @app.errorhandler(500)
    def internal_error(error):
        """500错误处理（页面 → 错误页；API → JSON）"""
        if _prefers_json_error():
            return {"error": "Internal server error", "code": 500}, 500
        return _render_error_page(500, "服务器出错了", "服务器处理请求时出错，请稍后重试。")

    # ADR-0011：静态资源版本化 URL（?v=mtime），配合长缓存
    _static_root = Path(app.static_folder)

    @app.context_processor
    def inject_static_url():
        def static_url(filename):
            version = 0
            try:
                version = int((_static_root / filename).stat().st_mtime)
            except OSError:
                pass
            return f"/static/{filename}?v={version}"

        return {"static_url": static_url}

    return app


# --- 进程管理（nginx 风格 start / quit / reload；新增能力，不改变前台运行方式）---

_BASE_DIR = Path(__file__).resolve().parent
_PID_FILE = _BASE_DIR / "Module" / "data" / "app.pid"
_SERVER_LOG = _BASE_DIR / "Module" / "log" / "server-stdout.log"


def _read_pid():
    try:
        return int(_PID_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _is_running(pid):
    """跨平台判定进程是否存活（Windows 用 tasklist，避免 os.kill(pid,0) 误杀）"""
    if not pid:
        return False
    try:
        if sys.platform == "win32":
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return str(pid) in result.stdout
        os.kill(pid, 0)
        return True
    except OSError:
        return False
    except Exception:
        return False


def _cmd_quit():
    """停止后台服务（执行完即退出）"""
    pid = _read_pid()
    if not pid or not _is_running(pid):
        _PID_FILE.unlink(missing_ok=True)
        print("服务未运行")
        return 0
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            text=True,
        )
    else:
        try:
            os.kill(pid, 15)
        except OSError:
            pass
    _PID_FILE.unlink(missing_ok=True)
    print(f"已停止服务 PID={pid}")
    return 0


def _cmd_start():
    """守护方式启动服务（生产模式，无 reloader），命令立即返回"""
    pid = _read_pid()
    if pid and _is_running(pid):
        print(f"服务已在运行 PID={pid}，如需重启请执行: app.py reload")
        return 1
    _SERVER_LOG.parent.mkdir(parents=True, exist_ok=True)
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    with open(_SERVER_LOG, "a", encoding="utf-8") as log:
        proc = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "_serve"],
            cwd=str(_BASE_DIR),
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=flags,
            close_fds=True,
        )
    _PID_FILE.write_text(str(proc.pid), encoding="utf-8")
    # 等待端口绑定，尽早暴露启动失败（例如端口被占用）
    time.sleep(1.0)
    if proc.poll() is not None:
        _PID_FILE.unlink(missing_ok=True)
        print(f"启动失败（退出码 {proc.returncode}），详见日志: {_SERVER_LOG}")
        return 1
    print(f"启动成功 PID={proc.pid}  http://127.0.0.1:20999  日志: {_SERVER_LOG}")
    return 0


def _cmd_reload():
    """重载：停止旧进程后按当前代码重新启动（执行完即退出）"""
    pid = _read_pid()
    if pid and _is_running(pid):
        _cmd_quit()
    return _cmd_start()


def _serve(production_mode):
    """实际运行服务器（前台；也是 start 的后台子进程入口）"""
    app = create_app()

    # ADR-0012：后台预热画廊扫描缓存，消除发现区冷启动的首访等待
    def _prewarm_gallery_cache():
        try:
            from Module.core.gallery_service import GalleryService

            svc = GalleryService()
            root = svc.get_gallery_root()
            if root:
                svc.get_all_subfolders_recursive(root)
        except Exception:
            pass

    import threading

    threading.Thread(target=_prewarm_gallery_cache, daemon=True).start()

    # 监听地址：Windows 的 IPv6 套接字默认 IPV6_V6ONLY=1，"::" 只收 IPv6
    # （localhost 解析到 ::1 可访问，但 127.0.0.1 等 IPv4 地址不可访问）；
    # 故 Windows 改用 IPv4 全接口，Linux/macOS 保持 "::" 双栈监听（v6only=0）。
    _host = "0.0.0.0" if sys.platform == "win32" else "::"
    app.run(
        host=_host,
        port=20999,
        debug=not production_mode,  # 生产模式禁用调试
        use_reloader=not production_mode,
    )


def main(argv=None):
    """
    命令行入口：
        py app.py start   后台启动（执行完即退出）
        py app.py quit    停止服务（执行完即退出）
        py app.py reload  重启服务（执行完即退出）
        py app.py [--production]  前台运行（原有方式，兼容保留）
    """
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "start":
        return _cmd_start()
    if args and args[0] == "quit":
        return _cmd_quit()
    if args and args[0] == "reload":
        return _cmd_reload()
    if args and args[0] == "_serve":
        _serve(production_mode=True)
        return 0
    _serve(production_mode="--production" in args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
