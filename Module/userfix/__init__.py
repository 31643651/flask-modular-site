# 用户反馈模块
from .userfix import userfix_bp
from .admin_view import userfix_admin_bp

__all__ = ['userfix_bp', 'userfix_admin_bp']