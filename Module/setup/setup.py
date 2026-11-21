"""
初始配置路由模块

提供初始配置页面，引导用户完成管理员账户创建和服务器名称设置。
"""

from flask import Blueprint, render_template, request, redirect, url_for, session
from werkzeug.security import generate_password_hash
from Module.common.file_utils import write_json_file
from Module.common.db_utils import execute
from Module.common.paths import CONFIG_FILE

# 创建蓝图对象
setup_bp = Blueprint(
    "setup", __name__, url_prefix="/setup", template_folder="templates"
)


@setup_bp.route("/", methods=["GET", "POST"])
def index():
    """初始配置页面"""
    # 检查是否已完成配置
    if CONFIG_FILE.exists():
        return redirect(url_for("user.login"))

    if request.method == "POST":
        step = request.form.get("step", "1")

        if step == "1":
            # 步骤1：创建管理员账户
            password = request.form.get("password")
            confirm_password = request.form.get("confirm_password")
            admin_verify_enabled = request.form.get("admin_verify_enabled") == "on"

            # 验证
            if not password:
                return render_template(
                    "setup/setup.html", step=1, error="密码不能为空"
                )
            if password != confirm_password:
                return render_template(
                    "setup/setup.html", step=1, error="两次输入的密码不一致"
                )

            # 存储到 session（I2：存哈希而非明文——session 是签名但不加密的客户端
            # cookie，浏览器可读；避免明文密码滞留于持久化会话）
            session["setup_password"] = generate_password_hash(password)
            session["setup_admin_verify"] = admin_verify_enabled

            # 跳转到步骤2
            return render_template("setup/setup.html", step=2)

        elif step == "2":
            # 步骤2：设置服务器名称
            server_name = request.form.get("server_name", "Web")

            # 从 session 获取步骤1的数据
            password = session.get("setup_password")
            admin_verify_enabled = session.get("setup_admin_verify", False)

            # 创建管理员用户（session 中存的已是 werkzeug 哈希，直接入库；
            # 不能再包一层 generate_password_hash，否则二次哈希导致无法登录——I2）
            try:
                execute(
                    "INSERT INTO users (id, username, password, role, enabled, is_superadmin) VALUES (?, ?, ?, ?, ?, ?)",
                    (1, "admin", password, "admin", 1, 1),
                )
            except Exception as e:
                return render_template(
                    "setup/setup.html", step=2, error=f"创建管理员用户失败: {str(e)}"
                )

            # 创建配置文件
            config = {
                "paths": {
                    "book_data_path": "",
                    "book_static_path": "",
                    "gallery_root_path": "",
                },
                "settings": {
                    "admin_verify_enabled": admin_verify_enabled,
                    "wallpaper_enabled": False,
                    "books_enabled": False,
                    "gallery_enabled": False,
                    "mounted_pages_enabled": False,
                },
                "wallpaper": {"enabled": False, "path": "Module/static/wallpaper"},
                "mounted_pages": [],
                "config": {"server_name": server_name},
            }

            if not write_json_file(CONFIG_FILE, config):
                return render_template(
                    "setup/setup.html", step=2, error="保存配置文件失败"
                )

            # 清理 session
            session.pop("setup_password", None)
            session.pop("setup_admin_verify", None)

            # 跳转到登录页面
            return redirect(url_for("user.login"))

    # GET 请求，显示步骤1
    return render_template("setup/setup.html", step=1)
