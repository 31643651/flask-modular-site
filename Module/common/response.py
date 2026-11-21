# Module/common/response.py
"""
统一响应格式模块

提供标准化的 JSON 响应格式，所有 API 响应必须遵循：
{
    "code": 0,
    "data": { ... },
    "msg": "操作成功"
}
"""

from enum import IntEnum
from flask import jsonify


class ErrorCode(IntEnum):
    """错误码枚举"""

    SUCCESS = 0
    BAD_REQUEST = 400
    UNAUTHORIZED = 401
    FORBIDDEN = 403
    NOT_FOUND = 404
    INTERNAL_ERROR = 500
    # 模块特定错误码
    ADMIN_CONFIG_ERROR = 1001
    GALLERY_SCAN_ERROR = 2001
    BOOK_NOT_FOUND = 3001


def success_response(data=None, message="操作成功", code=ErrorCode.SUCCESS):
    """
    返回成功 JSON 响应

    Args:
        data: 响应数据
        message: 成功消息
        code: 错误码（默认 SUCCESS）

    Returns:
        tuple: (JSON响应, 状态码)
    """
    return jsonify({"code": int(code), "data": data, "msg": message}), 200


def error_response(message="操作失败", code=ErrorCode.INTERNAL_ERROR, status_code=400):
    """
    返回错误 JSON 响应

    Args:
        message: 错误消息
        code: 错误码
        status_code: HTTP 状态码

    Returns:
        tuple: (JSON响应, 状态码)
    """
    return jsonify({"code": int(code), "data": None, "msg": message}), status_code


def paginated_response(data, page, per_page, total):
    """
    返回分页 JSON 响应

    Args:
        data: 当前页数据列表
        page: 当前页码
        per_page: 每页条数
        total: 总条数

    Returns:
        tuple: (JSON响应, 状态码)
    """
    return jsonify(
        {
            "code": int(ErrorCode.SUCCESS),
            "data": {
                "items": data,
                "pagination": {
                    "page": page,
                    "per_page": per_page,
                    "total": total,
                    "pages": (total + per_page - 1) // per_page if per_page > 0 else 0,
                },
            },
            "msg": "操作成功",
        }
    ), 200
