"""
网络工具（单一事实来源）

get_client_ip：仅在 TRUST_PROXY_HEADERS=1（部署于可信反向代理之后）时读取
X-Forwarded-For / X-Real-IP，否则回退 remote_addr，避免伪造代理头绕过限速。
ipguard 与 AdminService 统一使用本实现，不再各自维护副本。
"""

import os


def get_client_ip(req):
    """解析客户端真实 IP（req 为 Flask request 或等价对象）"""
    if os.environ.get("TRUST_PROXY_HEADERS", "0") == "1":
        forwarded_for = req.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        real_ip = req.headers.get("X-Real-IP")
        if real_ip:
            return real_ip.strip()
    return req.remote_addr or ""
