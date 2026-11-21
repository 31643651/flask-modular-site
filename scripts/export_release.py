"""
导出可发布的 zip 包（一键打包）。

用法：
    py -3.12 scripts/export_release.py
    py -3.12 scripts/export_release.py --name my-site --output dist/my-site.zip

规则：
- 包含：源码、模板、静态资源（用户壁纸除外）、文档、测试、脚本、requirements、LICENSE、README；
- 剔除：.git/缓存/虚拟环境、运行数据（SQLite/PID/日志/用户上传/壁纸）、
        运行配置（Module/json）、内部规划与代理文档（docs/superpowers、AGENTS.md、tasks 账本等）；
- 打包后执行"禁入项"安全扫描，发现敏感/运行文件立即失败并删除产物。
"""

import argparse
import sys
import zipfile
from datetime import datetime
from fnmatch import fnmatch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 目录名黑名单（任意层级命中即排除）
EXCLUDED_DIR_NAMES = {
    ".git",
    ".pytest_cache",
    ".ruff_cache",
    ".superpowers",
    "__pycache__",
    "dist",
    "imagetest",
    "sdinspector",
    "待处理文件",
    ".venv",
    "venv",
    "env",
    ".idea",
    ".vscode",
    "node_modules",
}

# 相对路径前缀黑名单（运行数据与内部规划）
EXCLUDED_PATH_PREFIXES = (
    "Module/data/",
    "Module/json/",
    "Module/log/log/",
    "Module/userfix/submissions/",
    "Module/static/wallpaper/",
    "docs/superpowers/",
)

# 文件名黑名单（开发流程/代理/临时文件）
EXCLUDED_FILE_NAMES = {
    "AGENTS.md",
    "tasks.json",
    "tasks.schema.md",
    "CURRENT_TASK.md",
    "cookies.txt",
    "review_diff.tmp",
    "nul",
    # 开发期工具与流程文档，不随发布包分发
    "session.py",
    "可复用开发流程标准与Python移植.md",
}

# 通配符黑名单（日志/缓存/临时/运行时文件）
EXCLUDED_FILE_PATTERNS = ("*.pyc", "*.pyo", "*.log", "*.tmp", "*.pid")

# 打包产物必须包含的文件（缺失即失败）
REQUIRED_FILES = (
    "app.py",
    "requirements.txt",
    "requirements-dev.txt",
    "LICENSE",
    "README.md",
    "docs/modularity.md",
    "tests/conftest.py",
)


def should_exclude(rel_path):
    """判断仓库相对路径（POSIX 风格）是否应从发布包中剔除"""
    rel = rel_path.replace("\\", "/").strip("/")
    if not rel:
        return True

    parts = rel.split("/")
    if any(part in EXCLUDED_DIR_NAMES for part in parts):
        return True
    if rel in EXCLUDED_FILE_NAMES:
        return True
    if any(fnmatch(parts[-1], pattern) for pattern in EXCLUDED_FILE_PATTERNS):
        return True
    if any(rel == prefix.rstrip("/") or rel.startswith(prefix) for prefix in EXCLUDED_PATH_PREFIXES):
        return True
    return False


def _is_forbidden_zip_entry(name):
    """发布包安全扫描：敏感/运行时文件不得出现"""
    posix = name.replace("\\", "/")
    parts = posix.split("/")
    if any(part in {"__pycache__", ".git", "submissions", "wallpaper"} for part in parts):
        return True
    lowered = posix.lower()
    if lowered.endswith((".db", ".db-wal", ".db-shm", ".log", ".pid", ".pyc", ".pyo")):
        return True
    if "/Module/json/" in posix:
        return True
    if posix.endswith("cookies.txt") or posix.endswith("tasks.json"):
        return True
    return False


def collect_files(root=None):
    """收集待打包文件（返回 [(绝对路径, 相对路径)])"""
    root = Path(root or ROOT)
    files = []
    for path in sorted(root.rglob("*")):
        if path.is_dir():
            continue
        rel = path.relative_to(root).as_posix()
        if should_exclude(rel):
            continue
        files.append((path, rel))
    return files


def build_release(output_path, name="flask-modular-site", root=None):
    """
    构建发布包。

    Returns:
        dict: {files, bytes, zip_bytes, output}
    """
    root = Path(root or ROOT)
    output_path = Path(output_path)
    files = collect_files(root)
    missing = [f for f in REQUIRED_FILES if f not in {rel for _, rel in files}]
    if missing:
        raise RuntimeError(f"发布包缺少必需文件: {missing}")

    inner = name
    output_path.parent.mkdir(parents=True, exist_ok=True)
    total_bytes = 0
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, rel in files:
            zf.write(path, f"{inner}/{rel}")
            total_bytes += path.stat().st_size

    # 安全扫描
    with zipfile.ZipFile(output_path) as zf:
        bad = [n for n in zf.namelist() if _is_forbidden_zip_entry(n)]
    if bad:
        output_path.unlink(missing_ok=True)
        raise RuntimeError(f"发布包含有禁入文件，已删除产物: {bad[:5]}")

    return {
        "files": len(files),
        "bytes": total_bytes,
        "zip_bytes": output_path.stat().st_size,
        "output": output_path,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="导出可发布的 zip 包")
    parser.add_argument("--name", default="flask-modular-site", help="包内顶层目录名")
    parser.add_argument("--output", default=None, help="输出 zip 路径（默认 dist/<name>-<日期>.zip）")
    parser.add_argument("--date", default=None, help="日期标记（默认今天，格式 YYYYMMDD）")
    args = parser.parse_args(argv)

    stamp = args.date or datetime.now().strftime("%Y%m%d")
    inner = f"{args.name}-{stamp}"
    output = Path(args.output) if args.output else ROOT / "dist" / f"{inner}.zip"

    try:
        result = build_release(output, name=inner)
    except RuntimeError as exc:
        print(f"[export] 失败: {exc}", file=sys.stderr)
        return 1

    print(
        f"[export] 完成: {result['output']}  "
        f"文件 {result['files']} 个  "
        f"源 {result['bytes'] / 1024 / 1024:.2f} MB → zip {result['zip_bytes'] / 1024 / 1024:.2f} MB"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
