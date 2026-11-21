"""
分页工具模块

提供通用的分页辅助函数，用于列表端点。
"""

from flask import request


def get_pagination_params(req=None):
    """
    从请求中提取分页参数

    Args:
        req: Flask 请求对象（默认使用当前请求）

    Returns:
        tuple: (page, per_page) 元组
    """
    if req is None:
        from flask import request as req
    try:
        page = max(1, int(req.args.get('page', 1)))
    except (ValueError, TypeError):
        page = 1
    try:
        per_page = max(1, min(100, int(req.args.get('per_page', 20))))
    except (ValueError, TypeError):
        per_page = 20
    return page, per_page


def paginate_query(query_func, page=1, per_page=20, **kwargs):
    """
    通用分页包装器

    Args:
        query_func: 查询函数，接受 (offset, limit, **kwargs) 返回 (items, total)
        page: 页码
        per_page: 每页条数
        **kwargs: 传递给 query_func 的额外参数

    Returns:
        tuple: (items, pagination_meta) 元组
    """
    offset = (page - 1) * per_page
    items, total = query_func(offset=offset, limit=per_page, **kwargs)
    return items, format_pagination_meta(page, per_page, total)


def format_pagination_meta(page, per_page, total):
    """
    格式化分页元数据

    Args:
        page: 当前页码
        per_page: 每页条数
        total: 总条数

    Returns:
        dict: 分页元数据字典
    """
    return {
        "page": page,
        "per_page": per_page,
        "total": total,
        "pages": (total + per_page - 1) // per_page if per_page > 0 else 0
    }
