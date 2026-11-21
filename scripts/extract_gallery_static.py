"""
画廊模板静态资源提取器（ADR-0009 / 计划 G3、G4）。

用法：
    py -3.12 scripts/extract_gallery_static.py css   # 提取 index.html 的 <style> 区（已执行）
    py -3.12 scripts/extract_gallery_static.py js     # 整块提取 <script> 区，剥离注入三行

原则：
- 机械切割，字节级校验（提取出的内容必须与模板原区逐字节一致）；
- 被提取区内出现 Jinja 标签（{{ 或 {%）即报错退出——静态文件不会被 Jinja 渲染；
- 注入三行（serverPreferences/serverDeviceSpecific/csrfToken）留在模板内联，
  且必须先于外部 <script src>；
- 模板原位替换为 <link>/<script src> 引用行；
- 失败不写任何文件（先全部校验再落盘）。
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "Module/gallery/templates/gallery/index.html"
FAV_TEMPLATE = ROOT / "Module/gallery/templates/gallery/favorites.html"
CSS_OUT = ROOT / "Module/static/gallery/css/gallery.css"
FAV_CSS_OUT = ROOT / "Module/static/gallery/css/favorites.css"
JS_DIR = ROOT / "Module/static/gallery/js"
JS_OUT = JS_DIR / "gallery-page.js"
JS_HEADER = "/* gallery page script (ADR-0009) */\n"

# 必须保留在模板内联的注入三行（前缀匹配；契约测试锚定其文本形态）
INJECTION_PREFIXES = (
    "const serverPreferences =",
    "const serverDeviceSpecific =",
    "window.csrfToken =",
)


def die(msg):
    print(f"[extract] ERROR: {msg}", file=sys.stderr)
    raise SystemExit(1)


def check_no_jinja(chunk, where):
    if "{{" in chunk or "{%" in chunk:
        die(f"{where} 内含 Jinja 标签，不能提取为静态文件")


def extract_css(template, out, url):
    src = template.read_text(encoding="utf-8")
    if src.count("<style>") != 1 or src.count("</style>") != 1:
        die(f"{template.name} <style> 块数量异常：{src.count('<style>')} / {src.count('</style>')}")
    start = src.index("<style>") + len("<style>")
    end = src.index("</style>")
    css = src[start:end]
    check_no_jinja(css, "<style> 区")
    link = f'<link rel="stylesheet" href="{url}">'
    new_src = src[: src.index("<style>")] + link + src[end + len("</style>") :]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(css, encoding="utf-8")
    template.write_text(new_src, encoding="utf-8", newline="\n")
    back = out.read_text(encoding="utf-8")
    assert back == css, "CSS 提取字节校验失败"
    print(f"[extract] css OK: {len(css)} chars -> {out.relative_to(ROOT)}")


def extract_js():
    src = TEMPLATE.read_text(encoding="utf-8")
    if src.count("<script>") != 1 or src.count("</script>") != 1:
        die(
            f"index.html <script> 块数量异常："
            f"{src.count('<script>')} / {src.count('</script>')}"
        )
    s_open = src.index("<script>")
    s_close = src.index("</script>")
    body = src[s_open + len("<script>") : s_close]

    lines = body.splitlines(keepends=True)
    inj_idx = [
        i
        for i, line in enumerate(lines)
        if line.strip().startswith(INJECTION_PREFIXES)
    ]
    if len(inj_idx) != 3:
        die(f"注入行数量异常：期望 3，实际 {len(inj_idx)}")
    injected = "".join(lines[i] for i in inj_idx)
    rest = "".join(line for i, line in enumerate(lines) if i not in inj_idx)
    check_no_jinja(rest, "<script> 提取体")

    # 字节级校验：从原 script 内容中按序移除注入行后必须等于提取体（内容守恒）
    stripped = body
    for i in inj_idx:
        piece = lines[i]
        pos = stripped.index(piece)
        stripped = stripped[:pos] + stripped[pos + len(piece) :]
    assert stripped == rest, "JS 提取字节校验失败（内容不守恒）"

    JS_DIR.mkdir(parents=True, exist_ok=True)
    JS_OUT.write_text(JS_HEADER + rest, encoding="utf-8", newline="\n")

    replacement = (
        "<script>\n"
        + injected
        + "    </script>\n"
        + '    <script src="/static/gallery/js/gallery-page.js"></script>'
    )
    new_src = src[:s_open] + replacement + src[s_close + len("</script>") :]
    TEMPLATE.write_text(new_src, encoding="utf-8", newline="\n")

    written = JS_OUT.read_text(encoding="utf-8")
    assert written == JS_HEADER + rest, "JS 落盘字节校验失败"
    print(
        f"[extract] js OK: {len(rest)} chars -> {JS_OUT.relative_to(ROOT)}；"
        f"注入三行保留 {len(injected)} chars"
    )


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ("css", "css-fav", "js"):
        print("用法: py -3.12 scripts/extract_gallery_static.py css|css-fav|js")
        return 2
    if sys.argv[1] == "css":
        extract_css(TEMPLATE, CSS_OUT, "/static/gallery/css/gallery.css")
    elif sys.argv[1] == "css-fav":
        extract_css(FAV_TEMPLATE, FAV_CSS_OUT, "/static/gallery/css/favorites.css")
    else:
        extract_js()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
