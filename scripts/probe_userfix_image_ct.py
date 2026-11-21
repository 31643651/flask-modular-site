"""
探测 userfix 图片端点对"伪装成 .jpg 的 SVG"实际返回的 Content-Type。

目的：判断 userfix 上传的 SVG（被强制改名 .jpg）在管理后台被 <img> 渲染时，
浏览器到底拿到什么 Content-Type / 是否带 nosniff，从而确认是否存在存储型 XSS。

做法：用项目自带的 create_app 工厂 + Flask test client（与测试套件同一机制），
直接注入已认证会话，绕开网络与登录/动态验证码流程，GET 真实端点并打印响应头。

只读探测：不写任何业务数据；若发现该提交的图片目录不存在则优雅退出。
"""

import sys
import mimetypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# 待探测的提交与文件（昨天实际上传并被强制改名 .jpg 的 SVG）
SUBMISSION = "admin_2026-11-19_21-36-44_813315"
FILENAME = "image_1.jpg"


def main() -> int:
    from app import create_app

    app = create_app()
    app.config["TESTING"] = True

    # 先看磁盘上这个文件到底是什么内容
    fpath = (
        ROOT / "Module" / "userfix" / "submissions" / SUBMISSION / FILENAME
    )
    print("== 磁盘文件 ==")
    if fpath.exists():
        head = fpath.read_bytes()[:80]
        print(f"路径存在: {fpath}")
        print(f"大小: {fpath.stat().st_size} 字节")
        print(f"前 80 字节: {head!r}")
    else:
        print(f"路径不存在: {fpath}")

    # mimetypes 会如何推断这个扩展名（send_file 默认就靠它）
    print("\n== mimetypes.guess_type(%r) ==" % FILENAME)
    print(f"  -> {mimetypes.guess_type(FILENAME)}")

    # 用 test client 以已登录超管身份请求真实端点
    print("\n== test client 已认证请求 ==")
    with app.test_client() as c:
        with c.session_transaction() as s:
            s["user_id"] = 2
            s["username"] = "admin"
            s["role"] = "admin"
            s["verified"] = True
            s["csrf_token"] = "x"

        url = f"/userfix/image/{SUBMISSION}/{FILENAME}"
        resp = c.get(url, follow_redirects=False)
        print(f"GET {url}")
        print(f"  status: {resp.status_code}")
        if resp.status_code == 200:
            data = resp.data
            print(f"  Content-Type: {resp.headers.get('Content-Type')}")
            print(f"  X-Content-Type-Options: {resp.headers.get('X-Content-Type-Options')}")
            print(f"  CSP: {resp.headers.get('Content-Security-Policy')}")
            print(f"  实际字节数: {len(data)}")
            print(f"  实际前 60 字节: {data[:60]!r}")
            is_svg = b"<svg" in data[:2000]
            print(f"  响应体是 SVG 内容: {is_svg}")
        else:
            print(f"  Location: {resp.headers.get('Location')}")
            print(f"  body: {resp.data[:200]!r}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
