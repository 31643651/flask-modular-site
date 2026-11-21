"""
全站性能基线探测（只读，用于性能优化前后对比）。

用法：
    py -3.12 scripts/perf_baseline.py [用户名] [密码]

测量内容：
    - 关键页面 HTML 完整响应耗时（P50，多次采样，含 1 次预热）
    - 页面引用的 /static/ 资源耗时
    - 代表性图片资源耗时
    - 响应头缓存字段（Cache-Control / ETag / Last-Modified）

输出：每项 状态码 / 字节数 / P50 毫秒 / 缓存头摘要。
"""

import http.cookiejar
import os
import re
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:20999"

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

PAGES = [
    "/",
    "/user/profile",
    "/gallery",
    "/gallery/favorites",
    "/userfix",
    "/book",
]

STATIC_SAMPLES = [
    "/static/gallery/css/gallery.css",
    "/static/gallery/js/gallery-page.js",
    "/static/gallery/css/favorites.css",
]

API_SAMPLES = [
    "/gallery/api/random-images",
    "/api/mounted-pages",
    "/api/wallpaper/config",
]

IMAGE_PATTERN = re.compile(r'(?:src|href)="(/gallery/image/[^"]+)"')


def build_opener():
    jar = http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def _open(opener, path, data=None):
    """统一带浏览器 UA 的请求（规避 ipguard 的 Other-UA 第一防线）"""
    safe_path = urllib.parse.quote(path, safe="/%?=&")
    req = urllib.request.Request(
        BASE + safe_path, data=data, headers={"User-Agent": BROWSER_UA}
    )
    return opener.open(req, timeout=30)


def login(opener, username, password):
    # 先 GET 登录页拿 session cookie 与 CSRF token（/user/login 的 POST 仍校验 CSRF）
    with _open(opener, "/user/login") as resp:
        page = resp.read().decode("utf-8", "ignore")
    match = re.search(r'name="csrf_token"\s+value="([^"]+)"', page)
    if not match:
        print("[warn] 登录页未解析到 csrf_token，尝试无 token 提交")
        token = ""
    else:
        token = match.group(1)
    data = urllib.parse.urlencode(
        {"username": username, "password": password, "csrf_token": token}
    ).encode()
    with _open(opener, "/user/login", data=data) as resp:
        body = resp.read().decode("utf-8", "ignore")
    if "动态密钥验证" in body:
        print("[warn] 登录后落到动态验证页，请用普通用户（免验证）重跑")
    return body


def fetch(opener, path):
    started = time.perf_counter()
    try:
        with _open(opener, path) as resp:
            body = resp.read()
            status = resp.status
            headers = resp.headers
    except urllib.error.HTTPError as exc:  # 4xx/5xx 也要计时
        body = exc.read()
        status = exc.code
        headers = exc.headers
    elapsed_ms = (time.perf_counter() - started) * 1000
    return status, body, headers, elapsed_ms


def cache_summary(headers):
    parts = []
    for key in ("Cache-Control", "ETag", "Last-Modified"):
        val = headers.get(key)
        if val:
            parts.append(f"{key}={val[:40]}")
    return "; ".join(parts) or "无缓存头"


def measure(opener, path, samples=5):
    fetch(opener, path)  # 预热
    times = []
    status = size = 0
    headers = None
    for _ in range(samples):
        status, body, headers, ms = fetch(opener, path)
        times.append(ms)
        size = len(body)
    return status, size, statistics.median(times), headers


def main():
    if len(sys.argv) > 3:
        print("用法: py -3.12 scripts/perf_baseline.py [用户名] [密码]")
        print("未提供密码时读取环境变量 PERF_PASSWORD")
        return 2
    username = (
        sys.argv[1]
        if len(sys.argv) > 1
        else os.environ.get("PERF_USER", "uidadmin")
    )
    password = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("PERF_PASSWORD", "")
    if not password:
        print(
            "缺少登录密码：请传入第二个参数或设置环境变量 PERF_PASSWORD",
            file=sys.stderr,
        )
        return 2
    opener = build_opener()
    login(opener, username, password)

    print(f"基线 {BASE}  用户={username}")
    print(f"{'路径':44s} {'状态':4s} {'字节':>9s} {'P50(ms)':>8s}  缓存头")
    print("-" * 110)

    gallery_html = ""
    for path in PAGES:
        status, size, p50, headers = measure(opener, path)
        if path == "/gallery":
            _, gallery_html, _, _ = fetch(opener, path)
            gallery_html = gallery_html.decode("utf-8", "ignore")
        print(f"{path:44s} {status:<4d} {size:>9d} {p50:>8.1f}  {cache_summary(headers)}")

    print("-" * 110)
    for path in STATIC_SAMPLES:
        status, size, p50, headers = measure(opener, path)
        print(f"{path:44s} {status:<4d} {size:>9d} {p50:>8.1f}  {cache_summary(headers)}")

    print("-" * 110)
    for path in API_SAMPLES:
        status, size, p50, headers = measure(opener, path, samples=3)
        print(f"{path:44s} {status:<4d} {size:>9d} {p50:>8.1f}  {cache_summary(headers)}")

    images = IMAGE_PATTERN.findall(gallery_html)[:2]
    for path in images:
        status, size, p50, headers = measure(opener, path, samples=3)
        print(f"{path[:44]:44s} {status:<4d} {size:>9d} {p50:>8.1f}  {cache_summary(headers)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
