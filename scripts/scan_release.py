"""
发布包敏感信息扫描（只读）。

用法：
    py -3.12 scripts/scan_release.py <解压目录或 zip>

检查项：
1. 禁入文件：config.json / *.db / *.log / *.pid / cookies.txt / server_info.json /
   userfix_limits.json / gallery_preferences.json / AGENTS.md / tasks.json
2. 真实凭据：SECRET_KEY/密码/API Key/私钥块/常见令牌格式/开发期测试账号口令
3. 本机绝对路径：盘符路径（如 D:\\...、C:\\Users\\...）、/home/、/Users/
4. 个人信息线索：邮箱、手机号

退出码：发现 HIGH（禁入文件/真实凭据/绝对路径）→ 1；仅 INFO/WARN → 0。
"""

import re
import sys
import zipfile
from pathlib import Path

FORBIDDEN_NAMES = {
    "config.json",
    "cookies.txt",
    "server_info.json",
    "userfix_limits.json",
    "gallery_preferences.json",
    "AGENTS.md",
    "tasks.json",
}
FORBIDDEN_SUFFIXES = (".db", ".db-wal", ".db-shm", ".log", ".pid", ".pyc", ".env")
FORBIDDEN_PARTS = ("submissions", "wallpaper", "__pycache__", ".git")

SECRET_PATTERNS = [
    (re.compile(r"SECRET_KEY\s*=\s*['\"][^'\"]{6,}['\"]"), "硬编码 SECRET_KEY"),
    (re.compile(r"(?i)api[_-]?key\s*[:=]\s*['\"][^'\"]{8,}['\"]"), "硬编码 API Key"),
    (re.compile(r"(?i)password\s*[:=]\s*['\"][^'\"]{4,}['\"]"), "硬编码口令"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "私钥块"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AWS Access Key"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"), "GitHub Token"),
    (re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"), "API Secret Key"),
    # 开发期真实使用过的口令（拆分为拼接，避免扫描脚本自身命中）
    (re.compile("Dev" + "Admin#2026|Uid" + "Admin#2026"), "开发期真实使用过的口令"),
]

ABS_PATH_PATTERNS = [
    (re.compile(r"[A-Za-z]:\\Users\\"), "本机用户目录绝对路径"),
    (re.compile(r"D:\\1web app"), "本机项目绝对路径"),
    (re.compile(r"[/\\]home[/\\][A-Za-z0-9_.-]+"), "Linux 家目录路径"),
    (re.compile(r"/Users/[A-Za-z0-9_.-]+"), "macOS 家目录路径"),
]

PII_PATTERNS = [
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "邮箱地址"),
    (re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), "手机号"),
]

# 测试夹具中的占位口令属可接受的低风险线索（仅提示）
TEST_CRED_PATTERN = re.compile(r"\b(adminpw|pass123|testpass|password123)\b")

TEXT_SUFFIXES = {
    ".py", ".html", ".js", ".css", ".md", ".json", ".txt", ".ini", ".cfg",
    ".yaml", ".yml", ".toml", ".sh", ".ps1", ".bat", ".xml", ".svg",
}


def _iter_entries(target):
    target = Path(target)
    if target.is_file() and target.suffix.lower() == ".zip":
        with zipfile.ZipFile(target) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                yield info.filename, zf.read(info)
        return
    for path in sorted(target.rglob("*")):
        if path.is_file():
            yield path.relative_to(target).as_posix(), path.read_bytes()


def _text_of(raw):
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return raw.decode("gbk", errors="ignore")
        except Exception:
            return ""


def scan(target):
    findings = []  # (severity, kind, name, line_no, detail)

    for name, raw in _iter_entries(target):
        parts = name.split("/")
        base = parts[-1]
        if base in FORBIDDEN_NAMES or base.lower().endswith(FORBIDDEN_SUFFIXES):
            findings.append(("HIGH", "禁入文件", name, 0, base))
        if any(part in FORBIDDEN_PARTS for part in parts[:-1]):
            findings.append(("HIGH", "禁入目录", name, 0, "/".join(parts[:-1])))
        if base == "Module/json" or "/Module/json/" in name:
            findings.append(("HIGH", "运行配置目录", name, 0, "Module/json"))

        suffix = Path(base).suffix.lower()
        if suffix not in TEXT_SUFFIXES:
            continue
        text = _text_of(raw)
        if not text:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for pattern, label in SECRET_PATTERNS:
                if pattern.search(line):
                    findings.append(("HIGH", label, name, lineno, line.strip()[:160]))
            for pattern, label in ABS_PATH_PATTERNS:
                if pattern.search(line):
                    findings.append(("HIGH", label, name, lineno, line.strip()[:160]))
            for pattern, label in PII_PATTERNS:
                if pattern.search(line):
                    findings.append(("INFO", label, name, lineno, line.strip()[:160]))
            if TEST_CRED_PATTERN.search(line):
                findings.append(("INFO", "测试占位口令", name, lineno, line.strip()[:160]))
    return findings


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("用法: py -3.12 scripts/scan_release.py <解压目录或 zip>")
        return 2
    target = Path(args[0])
    if not target.exists():
        print(f"[scan] 目标不存在: {target}", file=sys.stderr)
        return 2

    findings = scan(target)
    high = [f for f in findings if f[0] == "HIGH"]
    for severity, kind, name, lineno, detail in findings:
        loc = f"{name}:{lineno}" if lineno else name
        print(f"[{severity}] {kind} @ {loc} -> {detail}")
    print(f"[scan] 共 {len(findings)} 条（HIGH {len(high)}）")
    return 1 if high else 0


if __name__ == "__main__":
    raise SystemExit(main())
