"""
管理后台主路由
"""

from flask import Blueprint, render_template, session, request
from Module.core.admin_service import AdminService
from Module.common.user_utils import require_superadmin, load_activities
from Module.common.security import csrf_protect

admin_bp = Blueprint(
    "admin", __name__, url_prefix="/admin", template_folder="templates"
)
_service = AdminService()


@admin_bp.before_request
def _admin_auth_check():
    return require_superadmin()


@admin_bp.route("")
@admin_bp.route("/")
def dashboard():
    check = require_superadmin()
    if check:
        return check
    username = session.get("username")
    _service.update_active_session(
        username, _service.get_real_ip(request), request.user_agent.string
    )
    _service.cleanup_old_sessions()
    server_info = _service.load_server_info()
    activities = load_activities()
    recent_activities = activities[:10]
    from Module.ipguard import ban_manager

    recent_bans = ban_manager.get_active_bans()[:20]
    active_users = list(_service.get_active_sessions().values())
    for user in active_users:
        try:
            from datetime import datetime

            last_activity = datetime.fromisoformat(user["last_activity"])
            user["last_activity"] = last_activity.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            user["last_activity"] = "未知"
    return render_template(
        "admin/dashboard.html",
        server_info=server_info,
        uptime=_service.get_uptime(),
        recent_activities=recent_activities,
        recent_bans=recent_bans,
        active_users=active_users,
        active_users_count=len(active_users),
    )


@admin_bp.route("/restart", methods=["POST"])
@csrf_protect
def restart():
    check = require_superadmin()
    if check:
        return check
    import os, sys

    if sys.platform == "win32":
        # Windows 下 os.execv 行为不定（旧进程未退出、新进程端口未释放），
        # 改用子进程方式重启：先拉起新实例，再硬终止当前进程（bug #23 + 修复轮 1）。
        # 必须用 os._exit 而非 sys.exit：app.run() 线程模式下每个请求在独立线程
        # 处理，sys.exit 在非主线程中只静默终止该线程，父进程不退出、端口不释放，
        # 新进程绑定失败 → 重启静默失效；os._exit 直接终止整个进程。
        # 硬终止安全：不跑 atexit 清理器，但本进程持有的 SQLite 连接为线程局部
        # （OS 在进程退出时回收文件句柄，WAL 模式下未提交事务由回滚机制兜底），
        # 无必须落盘的进程级状态。
        import subprocess

        subprocess.Popen([sys.executable] + sys.argv)
        os._exit(0)
    os.execv(sys.executable, [sys.executable] + sys.argv)
