"""
诊断本机 20999 端口 IPv4/IPv6 可达性（复现 / 验收两用，ADR 无需，纯诊断工具）。

用法：
    py -3.12 scripts/check_local_access.py

输出：
    - 127.0.0.1:20999 连接结果（IPv4）
    - localhost:20999 连接结果（按 getaddrinfo 全族依次尝试，模拟浏览器回退）
    - 本平台 AF_INET6 绑定 "::" 的 IPV6_V6ONLY 默认值（Windows 通常为 1，
      即 "::" 不收 IPv4 连接——这正是 127 无法访问的根因）

退出码：全部可达 0；任一不可达 1（可作为修复前红 / 修复后绿的门禁）。
"""

import socket
import sys

PORT = 20999


def check(host, timeout=2.0):
    """依次尝试 getaddrinfo 返回的所有地址，返回 (是否成功, 说明)"""
    try:
        infos = socket.getaddrinfo(host, PORT, type=socket.SOCK_STREAM)
    except OSError as exc:
        return False, f"解析失败: {exc}"
    last_err = None
    tried = []
    for family, _, _, _, addr in infos:
        sock = socket.socket(family, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        try:
            sock.connect(addr)
            tried.append(f"{addr[0]} OK")
            return True, "；".join(tried)
        except OSError as exc:
            tried.append(f"{addr[0]} 失败({exc.errno})")
            last_err = exc
        finally:
            sock.close()
    return False, f"全部失败: {'；'.join(tried)}"


def v6only_default():
    """本平台 AF_INET6 绑 '::' 的 IPV6_V6ONLY 默认值"""
    try:
        sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        try:
            sock.bind(("::", 0))
            return sock.getsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY)
        finally:
            sock.close()
    except OSError as exc:
        return f"不可测: {exc}"


def main():
    results = {}
    for host in ("127.0.0.1", "localhost"):
        ok, detail = check(host)
        results[host] = ok
        print(f"[{'PASS' if ok else 'FAIL'}] {host}:{PORT} -> {detail}")

    print(f"[info] IPV6_V6ONLY 默认值 = {v6only_default()}（1 表示 '::' 不收 IPv4）")

    if all(results.values()):
        print("[result] 本机 IPv4 与 localhost 均可访问")
        return 0
    print("[result] 存在不可访问的入口")
    return 1


if __name__ == "__main__":
    sys.exit(main())
