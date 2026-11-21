"""
日志模块实现

本模块负责记录所有非 200 状态码的请求日志。
日志使用 structlog 输出 Logfmt 结构化格式，按天滚动存储。
"""

import logging
import sys
import structlog
from datetime import datetime, timezone
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

# ============================================================================
# 配置
# ============================================================================
# 基础目录路径
BASE_DIR = Path(__file__).parent.parent.parent
# 日志模块目录
LOG_MODULE_DIR = Path(__file__).parent
# 日志文件路径（按天滚动）
LOG_FILE = LOG_MODULE_DIR / "app.log"


def _add_timestamp(_, __, event_dict):
    """
    添加 ISO 8601 UTC 时间戳

    Args:
        _: 日志器
        __: 日志方法名
        event_dict: 事件字典

    Returns:
        dict: 添加时间戳后的事件字典
    """
    event_dict["timestamp"] = datetime.now(timezone.utc).isoformat()
    return event_dict


def configure_logging(enable_file_logging=True):
    """
    配置 structlog 与根 logger，输出 Logfmt 结构化日志

    - structlog 生成与第三方 stdlib 日志统一经 ProcessorFormatter 输出 Logfmt
    - 控制台 + 文件（按天滚动，保留 7 天）
    - werkzeug 日志走根 logger 结构化管道，仅保留 WARNING 及以上
    - enable_file_logging 为 False 时仅保留控制台日志（用于调试重载器父进程，
      避免父子进程同时打开 app.log 导致 Windows 下按天滚动重命名失败）
    """
    # 公共处理器链（structlog 生成 + 第三方日志统一）
    shared_processors = [
        structlog.stdlib.add_log_level,
        _add_timestamp,
        structlog.processors.format_exc_info,
        structlog.processors.StackInfoRenderer(),
        structlog.stdlib.ProcessorFormatter.remove_processors_meta,
        structlog.processors.LogfmtRenderer(
            sort_keys=True,
            key_order=["timestamp", "level", "event"],
        ),
    ]

    # 配置 structlog
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            _add_timestamp,
            structlog.processors.format_exc_info,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=shared_processors,
        foreign_pre_chain=[
            structlog.stdlib.add_log_level,
            _add_timestamp,
            structlog.processors.format_exc_info,
            structlog.processors.StackInfoRenderer(),
        ],
    )

    # 配置根 logger：清除原处理器，添加控制台与文件处理器
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.handlers.clear()

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # 仅在需要时创建文件处理器，避免调试重载器父子进程同时占用 app.log
    if enable_file_logging:
        file_handler = TimedRotatingFileHandler(
            str(LOG_FILE), when="midnight", backupCount=7, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

    # werkzeug 日志统一走根 logger 结构化管道（仅保留 WARNING 及以上避免访问日志刷屏）
    werkzeug_logger = logging.getLogger("werkzeug")
    werkzeug_logger.handlers.clear()
    werkzeug_logger.setLevel(logging.WARNING)
    werkzeug_logger.propagate = True


def log_request(logger, response, request_time):
    """
    记录请求日志（结构化字段）

    Args:
        logger: structlog 日志器
        response: Flask 响应对象
        request_time: 请求时间戳
    """
    # 只记录非 200 和非 304 状态码的响应
    if response.status_code != 200 and response.status_code != 304:
        from flask import request
        import re

        # 清理路径和IP中的控制字符，防止日志注入
        safe_path = re.sub(r"[\x00-\x1f\x7f]", "", request.path)
        safe_ip = re.sub(r"[\x00-\x1f\x7f]", "", request.remote_addr or "")

        log = logger.bind(
            method=request.method,
            path=safe_path,
            status=response.status_code,
            ip=safe_ip,
        )
        if 400 <= response.status_code < 500:
            log.warning("request_handled")
        elif response.status_code >= 500:
            log.error("request_handled")
        else:
            log.info("request_handled")

    # 重要：不修改响应内容，原样返回
    return response


def register_log_middleware(app, enable_file_logging=True):
    """
    注册日志中间件到 Flask 应用

    Args:
        app: Flask 应用实例
        enable_file_logging: 是否启用文件日志（默认 True，重载器父进程应传 False）
    """
    configure_logging(enable_file_logging=enable_file_logging)
    logger = structlog.get_logger("request_logger")

    @app.after_request
    def log_response(response):
        """在响应后记录日志（不修改响应内容）"""
        return log_request(logger, response, datetime.now().isoformat())
