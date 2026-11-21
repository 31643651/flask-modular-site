"""
verify_mounted_spa.py — 真实构建包挂载冒烟验证（挂载纯前端站优化·任务 5）

不进 pytest（依赖外网与真实构建资产），作为独立冒烟脚本：

    py scripts/verify_mounted_spa.py

阶段 1：抓取 https://it-tools.tech/ 的 index.html，提取站根绝对引用的
        同源静态资源（.js/.css/.webmanifest/.png/.ico/.svg）逐个下载到
        待处理文件/itools-dist/（保持相对路径结构，如 assets/index-xxx.js），
        连同 index.html 本身（挂载根需要）。网络失败重试 2 次，仍失败则如实
        输出 FAIL 备案（不伪造 PASS），对应断言按失败计。
阶段 2：进程内验证（import app.create_app + test client）：
        - 注入两条挂载记录（patch Module.index.index.load_config，功能开关走
          真实 config 的 mounted_pages_enabled=true，不 patch）；
        - 临时创建验证用户（role='user'——最小权限，check_auth 仅 admin 需要
          verified；test client session 注入登录态）；
        - patch 掉 ipguard 的 _handle_request（仅豁免限流中间件本身，认证
          before_request 与被测挂载链路不变；否则同 IP 连续请求触发第二防线
          429，冒烟无法进行；ipguard 代码零改动，脚本 finally 还原）；
        - 六条断言（itools HTML 重写/JS/CSS + sdinspector 302/JS/CSS），
          任何失败 exit 1；
        - finally：删除临时用户并核验删除成功（活动日志留痕可接受）。
"""

import re
import secrets
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DIST_DIR = ROOT / "待处理文件" / "itools-dist"
IT_TOOLS_BASE = "https://it-tools.tech"
ASSET_SUFFIX_RE = re.compile(
    r'(?:src|href)="(/[^"]+\.(?:js|css|webmanifest|png|ico|svg))"'
)
UA = "Mozilla/5.0 (spa-mount-verify)"


def _fetch(url, attempts=3, timeout=30):
    """带重试的 GET（初始 + 重试 2 次），返回 bytes 或 None"""
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except Exception as e:  # noqa: BLE001 — 网络失败逐次重试后如实上报
            print(f"    [网络] 第 {i + 1} 次请求失败 {url}: {e}")
            if i < attempts - 1:
                time.sleep(2 * (i + 1))
    return None


def stage1_download():
    """抓取 it-tools 真实构建资产到 DIST_DIR，返回 (index_html_bytes, 下载清单)"""
    print("[阶段 1] 抓取 it-tools.tech 真实构建资产...")
    html_bytes = _fetch(IT_TOOLS_BASE + "/")
    if html_bytes is None:
        print("    [网络 FAIL] it-tools.tech 首页抓取失败（重试 2 次后仍失败），备案")
        return None, []

    html_text = html_bytes.decode("utf-8", errors="replace")
    dist_html_path = DIST_DIR / "index.html"
    dist_html_path.parent.mkdir(parents=True, exist_ok=True)
    dist_html_path.write_bytes(html_bytes)

    manifest_paths = []
    seen = {"/"}
    for path in ASSET_SUFFIX_RE.findall(html_text):
        if path in seen:
            continue
        seen.add(path)
        rel = path.lstrip("/")
        target = DIST_DIR / rel
        data = _fetch(IT_TOOLS_BASE + path)
        if data is None:
            print(f"    [网络 FAIL] 资产下载失败（重试 2 次后仍失败），备案: {path}")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        manifest_paths.append((path, len(data)))
        print(f"    [下载] {path} -> {rel} ({len(data)} bytes)")
    print(f"    [下载] / -> index.html ({len(html_bytes)} bytes)")
    return html_text, manifest_paths


def stage2_verify():
    """进程内挂载验证：六条断言，返回失败列表（空 = 全过）"""
    print("\n[阶段 2] 进程内挂载验证（create_app + test client）...")

    import Module.index.index as index_mod
    from Module.common import db_utils
    from werkzeug.security import generate_password_hash

    import Module.ipguard.middleware as ipguard_mw

    # 汇总待断言的真实 hash 资源名
    itools_html = (DIST_DIR / "index.html").read_text(encoding="utf-8")
    m_js = re.search(r'src="/assets/(index-[A-Za-z0-9._-]+\.js)"', itools_html)
    m_css = re.search(r'href="/assets/(index-[A-Za-z0-9._-]+\.css)"', itools_html)
    sd_html = (ROOT / "sdinspector" / "index.html").read_text(encoding="utf-8")
    m_sd_js = re.search(r'src="static/(index\.[A-Za-z0-9]+\.(?:js))"', sd_html)
    m_sd_css = re.search(r'href="static/(index\.[A-Za-z0-9]+\.(?:css))"', sd_html)
    if not all([m_js, m_css, m_sd_js, m_sd_css]):
        return ["前置失败: 无法从 index.html 解析出 hash 资源名"]
    itools_js, itools_css = m_js.group(1), m_css.group(1)
    sd_js, sd_css = m_sd_js.group(1), m_sd_css.group(1)

    from app import create_app

    app = create_app()

    # 注入挂载记录：patch index.py 自带的 load_config（挂载列表口径）；
    # 功能开关（mounted_pages_enabled）走真实 config 的 config_utils 口径，不 patch
    original_load_config = index_mod.load_config
    index_mod.load_config = lambda: {
        "mounted_pages": [
            {"name": "itools", "path": "待处理文件/itools-dist", "type": "directory"},
            {"name": "sdinspector", "path": "sdinspector", "type": "directory"},
        ]
    }

    # 豁免 ipguard 限流（中间件闭包按模块全局名调用 _handle_request，patch 生效）：
    # 冒烟同 IP 连续请求会触发第二防线 429；仅豁免该中间件，认证检查不受影响。
    original_handle_request = ipguard_mw._handle_request
    ipguard_mw._handle_request = lambda: None

    # 临时验证用户（role='user' 最小权限；完事删除并核验）
    username = f"_spa_verify_{int(time.time())}"
    password = secrets.token_hex(16)
    db_utils.execute(
        "INSERT INTO users (username, password, role, enabled, is_superadmin)"
        " VALUES (?, ?, 'user', 1, 0)",
        (username, generate_password_hash(password)),
    )
    row = db_utils.query("SELECT id FROM users WHERE username = ?", (username,))
    user_id = row[0]["id"] if row else None
    print(f"    [临时用户] 已创建 {username} (id={user_id}, role=user)")

    failures = []
    try:
        client = app.test_client()
        with client.session_transaction() as sess:
            sess["user_id"] = user_id
            sess["username"] = username
            sess["role"] = "user"
            sess["verified"] = True

        def _check(label, cond, detail):
            status = "PASS" if cond else "FAIL"
            print(f"    [{status}] {label}  {detail}")
            if not cond:
                failures.append(f"{label}: {detail}")

        # ① itools HTML：200 且站根绝对引用被重写为挂载前缀（真实 hash 文件名）
        r = client.get("/itools/")
        body = r.data.decode("utf-8", errors="replace")
        _check(
            "① /itools/ 200 且含重写后的真实 hash JS 引用",
            r.status_code == 200
            and f'src="/itools/assets/{itools_js}"' in body,
            f"status={r.status_code}, 期望含 src=\"/itools/assets/{itools_js}\"",
        )

        # ② itools JS：200 且 content-type 为 text/javascript
        r = client.get(f"/itools/assets/{itools_js}")
        ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip()
        _check(
            f"② /itools/assets/{itools_js} 200 + text/javascript",
            r.status_code == 200 and ctype == "text/javascript",
            f"status={r.status_code}, content-type={ctype}",
        )

        # ③ itools CSS：200 且 content-type 为 text/css
        r = client.get(f"/itools/assets/{itools_css}")
        ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip()
        _check(
            f"③ /itools/assets/{itools_css} 200 + text/css",
            r.status_code == 200 and ctype == "text/css",
            f"status={r.status_code}, content-type={ctype}",
        )

        # ④ sdinspector 根：302 重定向到带尾斜杠
        r = client.get("/sdinspector")
        _check(
            "④ /sdinspector 302 → /sdinspector/",
            r.status_code == 302 and r.headers.get("Location") == "/sdinspector/",
            f"status={r.status_code}, Location={r.headers.get('Location')}",
        )

        # ⑤ sdinspector JS：200 且 content-type 为 text/javascript
        r = client.get(f"/sdinspector/static/{sd_js}")
        ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip()
        _check(
            f"⑤ /sdinspector/static/{sd_js} 200 + text/javascript",
            r.status_code == 200 and ctype == "text/javascript",
            f"status={r.status_code}, content-type={ctype}",
        )

        # ⑥ sdinspector CSS：200 且 content-type 为 text/css
        r = client.get(f"/sdinspector/static/{sd_css}")
        ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip()
        _check(
            f"⑥ /sdinspector/static/{sd_css} 200 + text/css",
            r.status_code == 200 and ctype == "text/css",
            f"status={r.status_code}, content-type={ctype}",
        )
    finally:
        # 临时用户清理：与创建同口径的 execute，删除后核验归零
        db_utils.execute("DELETE FROM users WHERE username = ?", (username,))
        remaining = db_utils.query(
            "SELECT COUNT(*) AS n FROM users WHERE username = ?", (username,)
        )
        gone = remaining and remaining[0]["n"] == 0
        print(
            f"    [清理] 临时用户 {username} 已删除，残留计数 = "
            f"{remaining[0]['n'] if remaining else '?'}（{'已核验清零' if gone else '未清零!'}）"
        )
        if not gone:
            failures.append("临时用户清理失败")
        index_mod.load_config = original_load_config
        ipguard_mw._handle_request = original_handle_request

    return failures


def main():
    html_text, manifest = stage1_download()
    if html_text is None:
        failures = stage2_verify()
        # 首页下载失败时 itools 相关断言必然失败——按失败如实退出
        failures.append("阶段 1 网络失败（it-tools 首页），相关断言无法真实通过")
        print("\n[结果] FAIL（网络失败备案，未伪造 PASS）")
        return 1

    print(
        f"\n[阶段 1 完成] 共下载 {len(manifest) + 1} 个文件"
        f"（index.html + {len(manifest)} 资产），位于 {DIST_DIR}"
    )
    failures = stage2_verify()

    print("\n[结果] " + ("全部 PASS" if not failures else f"{len(failures)} 项 FAIL"))
    for f in failures:
        print(f"    - {f}")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
