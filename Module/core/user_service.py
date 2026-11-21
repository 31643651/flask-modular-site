"""
用户业务逻辑服务

从 user.py 提取的业务逻辑：认证、用户资料管理。
"""

import time
import threading

from Module.common.user_utils import load_users, get_user, verify_user, add_activity

_login_failures = {}
_login_lock = threading.Lock()
_LOGIN_FAIL_LIMIT = 8
_LOGIN_FAIL_WINDOW = 300


class UserService:
    """用户服务，支持依赖注入"""

    def __init__(self, user_utils=None):
        self.user_utils = user_utils or __import__('Module.common.user_utils', fromlist=['load_users', 'get_user', 'verify_user', 'add_activity'])

    def get_user(self, username):
        return self.user_utils.get_user(username)

    def authenticate(self, username, password):
        user = self.get_user(username)
        if not user:
            return (False, "用户不存在")
        if not user.get("enabled"):
            return (False, "账户已被禁用")
        if not self.user_utils.verify_user(username, password):
            return (False, "密码错误")
        return (True, "登录成功")

    def record_login_attempt(self, ip, failed):
        now = time.time()
        with _login_lock:
            if not failed:
                _login_failures.pop(ip, None)
                return True
            count, first = _login_failures.get(ip, (0, now))
            if now - first >= _LOGIN_FAIL_WINDOW:
                _login_failures[ip] = (1, now)
                return True
            count += 1
            _login_failures[ip] = (count, first)
            return count < _LOGIN_FAIL_LIMIT

    def is_locked_out(self, ip):
        now = time.time()
        with _login_lock:
            count, first = _login_failures.get(ip, (0, now))
            if now - first >= _LOGIN_FAIL_WINDOW:
                return False
            return count >= _LOGIN_FAIL_LIMIT

    def get_profile(self, username):
        user = self.get_user(username)
        if not user:
            return None
        return {k: v for k, v in user.items() if k != "password"}
