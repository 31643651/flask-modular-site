"""
初始配置模块

当 config.json 不存在时，引导用户完成管理员账户创建和服务器名称设置。
"""

from .setup import setup_bp

__all__ = ["setup_bp"]
