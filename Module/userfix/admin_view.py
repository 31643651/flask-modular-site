"""
管理后台用户反馈视图路由
"""

from flask import Blueprint, render_template, session, request, jsonify
from Module.core.userfix_service import UserfixService
from Module.common.user_utils import require_superadmin

userfix_admin_bp = Blueprint(
    "userfix_admin", __name__, url_prefix="/admin", template_folder="templates"
)
_service = UserfixService()


@userfix_admin_bp.route("/userfix")
def userfix_page():
    check = require_superadmin()
    if check:
        return check
    status_filter = request.args.get("status", "all")
    submissions = _service.list_submissions(status_filter)

    # 分页逻辑
    per_page = 20
    try:
        page = int(request.args.get("page", 1))
    except ValueError:
        page = 1
    total = len(submissions)
    total_pages = (total + per_page - 1) // per_page if total > 0 else 1
    page = max(1, min(page, total_pages))
    start = (page - 1) * per_page
    paginated = submissions[start : start + per_page]

    return render_template(
        "admin/userfix.html",
        submissions=paginated,
        status_filter=status_filter,
        page=page,
        total_pages=total_pages,
    )


@userfix_admin_bp.route("/userfix/api/update-status", methods=["POST"])
def update_status():
    check = require_superadmin()
    if check:
        return check
    data = request.get_json()
    submission_id = data.get("id")
    status = data.get("status")
    if not submission_id or not status:
        return jsonify({"success": False, "message": "缺少参数"})
    success, message = _service.update_submission_status(submission_id, status)
    return jsonify({"success": success, "message": message})


@userfix_admin_bp.route("/userfix/api/delete", methods=["POST"])
def delete_submission():
    check = require_superadmin()
    if check:
        return check
    data = request.get_json()
    submission_id = data.get("id")
    if not submission_id:
        return jsonify({"success": False, "message": "缺少参数"})
    success, message = _service.delete_submission(submission_id)
    return jsonify({"success": success, "message": message})
