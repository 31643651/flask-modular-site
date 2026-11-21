"""
response.py 统一响应格式单元测试
"""

import json
from flask import Flask

from Module.common.response import (
    ErrorCode,
    success_response,
    error_response,
    paginated_response,
)


def test_success_response_default():
    """默认成功响应"""
    app = Flask(__name__)
    with app.app_context():
        response, status = success_response()
        assert status == 200
        data = json.loads(response.get_data(as_text=True))
        assert data["code"] == 0
        assert data["data"] is None
        assert data["msg"] == "操作成功"


def test_success_response_with_data():
    """带数据的成功响应"""
    app = Flask(__name__)
    with app.app_context():
        response, status = success_response(data={"id": 1}, message="创建成功")
        assert status == 200
        data = json.loads(response.get_data(as_text=True))
        assert data["code"] == 0
        assert data["data"] == {"id": 1}
        assert data["msg"] == "创建成功"


def test_error_response_default():
    """默认错误响应"""
    app = Flask(__name__)
    with app.app_context():
        response, status = error_response()
        assert status == 400
        data = json.loads(response.get_data(as_text=True))
        assert data["code"] == 500
        assert data["data"] is None
        assert data["msg"] == "操作失败"


def test_error_response_custom():
    """自定义错误响应"""
    app = Flask(__name__)
    with app.app_context():
        response, status = error_response(
            message="未找到", code=ErrorCode.NOT_FOUND, status_code=404
        )
        assert status == 404
        data = json.loads(response.get_data(as_text=True))
        assert data["code"] == 404
        assert data["msg"] == "未找到"


def test_paginated_response():
    """分页响应"""
    app = Flask(__name__)
    with app.app_context():
        items = [{"id": 1}, {"id": 2}]
        response, status = paginated_response(items, page=1, per_page=10, total=25)
        assert status == 200
        data = json.loads(response.get_data(as_text=True))
        assert data["code"] == 0
        assert data["data"]["items"] == items
        pagination = data["data"]["pagination"]
        assert pagination["page"] == 1
        assert pagination["per_page"] == 10
        assert pagination["total"] == 25
        assert pagination["pages"] == 3  # ceil(25/10)


def test_paginated_response_zero_per_page():
    """每页为0时分页计算不报错"""
    app = Flask(__name__)
    with app.app_context():
        response, status = paginated_response([], page=1, per_page=0, total=0)
        assert status == 200
        data = json.loads(response.get_data(as_text=True))
        assert data["data"]["pagination"]["pages"] == 0


def test_error_code_enum():
    """错误码枚举值正确"""
    assert ErrorCode.SUCCESS == 0
    assert ErrorCode.BAD_REQUEST == 400
    assert ErrorCode.UNAUTHORIZED == 401
    assert ErrorCode.FORBIDDEN == 403
    assert ErrorCode.NOT_FOUND == 404
    assert ErrorCode.INTERNAL_ERROR == 500
    assert ErrorCode.ADMIN_CONFIG_ERROR == 1001
    assert ErrorCode.GALLERY_SCAN_ERROR == 2001
    assert ErrorCode.BOOK_NOT_FOUND == 3001
