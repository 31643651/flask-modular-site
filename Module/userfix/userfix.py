"""
用户反馈模块（路由层）

职责：参数解析、前置校验编排、HTTP 响应；
业务逻辑（配额/校验/落盘/清理）全部委托 Module.core.userfix_service.UserfixService。
"""

import threading
import time
from pathlib import Path

from flask import Blueprint, request, jsonify, session

from Module.core import userfix_service as uf_service
from Module.core.userfix_service import (
    ALLOWED_IMAGE_EXTENSIONS,
    DAILY_LIMIT,
    MAX_IMAGE_SIZE,
    UserfixService,
    _MAGIC_HEAD_LEN,
    get_image_mime,
    validate_image_bytes,
)

# 创建蓝图对象
userfix_bp = Blueprint("userfix", __name__, url_prefix="/userfix")

_service = UserfixService()


# ============================================================================
# 兼容薄封装（保留原模块级函数名，内部委托服务层）
# ============================================================================
def get_today_date():
    return _service.get_today_date()


def load_limits():
    return _service.load_limits()


def save_limits(limits):
    return _service.save_limits(limits)


def get_user_submission_count(username):
    return _service.get_user_submission_count(username)


def check_submission_limit(username):
    return _service.check_submission_limit(username)


def check_and_increment_submission(username):
    return _service.check_and_increment_submission(username)


def sanitize_dir_component(username):
    return _service.sanitize_dir_component(username)


def save_submission(username, text, images):
    return _service.save_submission(username, text, images)


def cleanup_old_submissions():
    return _service.cleanup_old_submissions()


# ============================================================================
# 后台清理线程（每天一次；清理逻辑在服务层）
# ============================================================================
def _submission_cleanup_worker():
    while True:
        time.sleep(86400)
        try:
            _service.cleanup_old_submissions()
        except Exception:
            pass


_cleanup_thread = threading.Thread(target=_submission_cleanup_worker, daemon=True)
_cleanup_thread.start()


# ============================================================================
# 路由
# ============================================================================
@userfix_bp.route("/check-limit", methods=["GET"])
def check_limit():
    """查询当前用户是否还能提交反馈，以及剩余次数"""
    if "username" not in session:
        return jsonify({"success": False, "message": "请先登录"})

    username = session.get("username")
    can_submit, remaining = check_submission_limit(username)
    return jsonify({"success": True, "can_submit": can_submit, "remaining": remaining})


@userfix_bp.route("/submit", methods=["POST"])
def submit():
    """
    提交 bug 或功能建议（multipart/form-data，text 必需、images 最多 6 张）

    校验顺序（ADR-0008 / bug #18）：文本 → 数量 → 大小 → 白名单+magic（全部前置到
    配额扣减之前，失败不消耗当日限额且不落盘）
    """
    if "username" not in session:
        return jsonify({"success": False, "message": "请先登录"})

    username = session.get("username")

    text = request.form.get("text", "").strip()
    if not text:
        return jsonify({"success": False, "message": "请输入内容"})

    MAX_TEXT_LENGTH = 10000
    if len(text) > MAX_TEXT_LENGTH:
        return jsonify(
            {
                "success": False,
                "message": f"内容长度超出限制（最多{MAX_TEXT_LENGTH}字符）",
            }
        )

    # 过滤空的表单 part，不计入 6 张上限、不参与校验
    images = [f for f in request.files.getlist("images") if f and f.filename]
    if len(images) > 6:
        return jsonify({"success": False, "message": "最多只能上传6张图片"})

    # 大小 + 白名单 + magic-bytes 前置校验；校验后回卷流供服务层复读
    for image_file in images:
        payload = image_file.read()
        if len(payload) > MAX_IMAGE_SIZE:
            return jsonify({"success": False, "message": "图片大小超出限制"})
        err = validate_image_bytes(image_file.filename, payload[:_MAGIC_HEAD_LEN])
        if err:
            return jsonify({"success": False, "message": err})
        image_file.stream.seek(0)

    # 所有校验通过后，原子地检查并递增提交计数
    can_submit, remaining = check_and_increment_submission(username)
    if not can_submit:
        return jsonify(
            {
                "success": False,
                "message": f"今日提交次数已用完（每日限制 {DAILY_LIMIT} 次），请明天再试",
            }
        )

    success, result = save_submission(username, text, images)
    if success:
        return jsonify(
            {"success": True, "message": "提交成功，感谢您的反馈！", "path": result}
        )
    return jsonify({"success": False, "message": f"提交失败: {result}"})


@userfix_bp.route("/image/<submission_id>/<filename>")
def serve_image(submission_id, filename):
    """提交图片服务（路径穿越防护 + 白名单扩展 + 内容复验 + 显式 MIME）"""
    from flask import send_file, abort

    if ".." in submission_id or "/" in submission_id or "\\" in submission_id:
        abort(400)
    if ".." in filename or "/" in filename or "\\" in filename:
        abort(400)

    ext = Path(filename).suffix.lower()
    mime = get_image_mime(ext)
    if ext not in ALLOWED_IMAGE_EXTENSIONS or not mime:
        abort(404)

    # 运行时读取服务模块属性，支持测试/部署重定向
    submissions_dir = uf_service.USERFIX_SUBMISSIONS_DIR
    image_path = submissions_dir / submission_id / filename

    if not image_path.exists() or not image_path.is_file():
        abort(404)
    try:
        image_path.resolve().relative_to(submissions_dir.resolve())
    except ValueError:
        abort(403)

    with open(image_path, "rb") as fh:
        head = fh.read(_MAGIC_HEAD_LEN)
    if validate_image_bytes(filename, head):
        abort(404)

    return send_file(image_path, mimetype=mime)
