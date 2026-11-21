"""
公开路径常量（单一事实来源）

三层语义不同，不要混用：
- AUTH_WHITELIST：免登录访问
- CSRF_EXEMPT_PATHS：免 CSRF 校验（仅登录/验证/setup）
- IPGUARD_WHITELIST_PREFIXES：不计入限流、不被封禁拦截的前缀

原值保持不变（行为不变），仅消除三处手工同步的副本。
"""

AUTH_WHITELIST = ("/user/login", "/user/verify", "/static", "/favicon.ico", "/setup")

CSRF_EXEMPT_PATHS = ("/user/login", "/user/verify", "/setup")

IPGUARD_WHITELIST_PREFIXES = (
    "/static/",
    "/favicon.ico",
    "/setup",
    "/ipguard/banned",
    "/ipguard/rate_limited",
)
