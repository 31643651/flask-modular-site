"""
日志模块

本模块负责记录所有非 200 状态码的请求日志。
日志使用 structlog 输出 Logfmt 结构化格式，按天滚动存储。
"""

from .log import register_log_middleware

__all__ = ["register_log_middleware"]
