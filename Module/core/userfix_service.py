"""
用户反馈业务逻辑服务（单一实现）

承载：配额计数、提交校验（扩展名白名单 + magic-bytes + 大小）、落盘、
元数据、过期清理。路由层只做参数解析与 HTTP 响应。

ADR-0008：服务层同样执行白名单/magic-bytes 校验（路由前置 + 写盘前双重防御），
校验失败不产生任何文件系统副作用。
"""

import json
import logging
import re
import shutil
import threading
from datetime import datetime, timedelta
from pathlib import Path

from Module.common.paths import BASE_DIR, USERFIX_LIMITS_FILE, USERFIX_SUBMISSIONS_DIR
from Module.common.file_utils import read_json_file, write_json_file
from Module.common.user_utils import is_superadmin

# 每日提交次数限制（非超级管理员）
DAILY_LIMIT = 3
# 允许上传的图片扩展名白名单（防止任意文件上传）
ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
# 单个图片文件大小上限（字节），默认 5MB
MAX_IMAGE_SIZE = 5 * 1024 * 1024
# 提交记录保留天数
RETENTION_DAYS = 30

# ADR-0008：白名单扩展 → 固定 MIME 映射（serve 显式传入，不依赖 mimetypes 猜测）
IMAGE_MIME_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
}

# ADR-0008：各扩展的真实文件头（magic-bytes）；.webp 需单独校验 RIFF+WEBP 双段
_IMAGE_MAGIC = {
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".gif": (b"GIF87a", b"GIF89a"),
    ".bmp": (b"BM",),
}
_MAGIC_HEAD_LEN = 16

_submission_lock = threading.Lock()

logger = logging.getLogger(__name__)

# 提交记录 ID 黑名单（路径分隔符/点号/空白与控制字符；允许非 ASCII 用户名目录）
_ILLEGAL_ID_CHARS = re.compile(r"[/\\.\s\x00-\x1f\x7f]")
# metadata 读取失败哨兵（与合法空 dict 区分）
_METADATA_READ_FAILED = object()


def validate_image_bytes(filename, head_bytes):
    """
    ADR-0008 图片内容校验：扩展名白名单 + magic-bytes 真实类型比对。

    Args:
        filename: 客户端原始文件名（取扩展名）
        head_bytes: 文件头字节（至少前 16 字节）

    Returns:
        str | None: 校验失败的错误信息；通过返回 None
    """
    ext = Path(filename or "").suffix.lower()
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        return f"不支持的图片格式：{ext or '无扩展名'}（仅支持 {'/'.join(sorted(ALLOWED_IMAGE_EXTENSIONS))}）"
    if ext == ".webp":
        if (
            len(head_bytes) >= 12
            and head_bytes[:4] == b"RIFF"
            and head_bytes[8:12] == b"WEBP"
        ):
            return None
        return "图片内容与扩展名不符"
    for sig in _IMAGE_MAGIC.get(ext, ()):  # 多候选签名（GIF87a/89a）
        if head_bytes[: len(sig)] == sig:
            return None
    return "图片内容与扩展名不符"


def get_image_mime(ext):
    """白名单扩展 → MIME（未知返回 None）"""
    return IMAGE_MIME_TYPES.get((ext or "").lower())


class UserfixService:
    """用户反馈服务，支持依赖注入"""

    def __init__(self, user_utils=None):
        self.user_utils = user_utils or __import__(
            "Module.common.user_utils", fromlist=["get_user", "is_superadmin"]
        )

    # --- 配额 ---
    def get_today_date(self):
        return datetime.now().strftime("%Y-%m-%d")

    def load_limits(self):
        return read_json_file(USERFIX_LIMITS_FILE, default={})

    def save_limits(self, limits):
        write_json_file(USERFIX_LIMITS_FILE, limits, ensure_ascii=False, indent=2)

    def get_user_submission_count(self, username):
        limits = self.load_limits()
        today = self.get_today_date()
        return limits.get(today, {}).get(username, 0)

    def check_submission_limit(self, username):
        user = self.user_utils.get_user(username)
        if not user:
            return (False, 0)
        if is_superadmin(user):
            return (True, -1)
        count = self.get_user_submission_count(username)
        remaining = DAILY_LIMIT - count
        return (remaining > 0, remaining)

    def check_and_increment_submission(self, username):
        with _submission_lock:
            user = self.user_utils.get_user(username)
            if not user:
                return (False, 0)
            if is_superadmin(user):
                return (True, -1)
            count = self.get_user_submission_count(username)
            if count >= DAILY_LIMIT:
                return (False, 0)
            limits = self.load_limits()
            today = self.get_today_date()
            if today not in limits:
                limits[today] = {}
            if username not in limits[today]:
                limits[today][username] = 0
            limits[today][username] += 1
            self.save_limits(limits)
            remaining = DAILY_LIMIT - count - 1
            return (True, remaining)

    # --- 落盘 ---
    @staticmethod
    def sanitize_dir_component(username):
        safe = "".join(c if (c.isalnum() or c in "_-") else "_" for c in username)
        return safe or "anonymous"

    def get_submissions_dir(self):
        """提交根目录（运行时读取模块属性，便于测试/配置重定向）"""
        return USERFIX_SUBMISSIONS_DIR

    def save_submission(self, username, text, images):
        """
        保存提交内容（文本 + 最多 6 张白名单图片 + metadata.json）。

        ADR-0008：非白名单扩展 / 内容与扩展名不符一律拒绝，不再改名保存；
        校验在建目录写盘前完成，失败无文件系统副作用。
        """
        try:
            user = self.user_utils.get_user(username)
            if not user:
                return (False, "用户不存在")

            # 写盘前复验（路由已前置校验，此处纵深防御）
            prepared = []
            for image_file in images:
                original_name = image_file.filename or ""
                if not original_name:
                    continue
                if len(prepared) >= 6:
                    break
                payload = image_file.read()
                if len(payload) > MAX_IMAGE_SIZE:
                    return (False, "图片大小超出限制")
                err = validate_image_bytes(original_name, payload[:_MAGIC_HEAD_LEN])
                if err:
                    return (False, err)
                prepared.append((Path(original_name).suffix.lower(), payload))

            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S_%f")
            safe_username = self.sanitize_dir_component(username)
            submissions_dir = self.get_submissions_dir()
            submission_dir = submissions_dir / f"{safe_username}_{timestamp}"
            submission_dir.mkdir(parents=True, exist_ok=True)
            try:
                text_file = submission_dir / "content.txt"
                with open(text_file, "w", encoding="utf-8") as f:
                    f.write(text)

                saved_images = []
                for idx, (ext, payload) in enumerate(prepared, 1):
                    image_path = submission_dir / f"image_{idx}{ext}"
                    with open(image_path, "wb") as f:
                        f.write(payload)
                    saved_images.append(f"image_{idx}{ext}")

                metadata = {
                    "username": username,
                    "timestamp": datetime.now().isoformat(),
                    "images": saved_images,
                }
                metadata_file = submission_dir / "metadata.json"
                with open(metadata_file, "w", encoding="utf-8") as f:
                    json.dump(metadata, f, ensure_ascii=False, indent=2)
            except Exception:
                shutil.rmtree(submission_dir, ignore_errors=True)
                raise

            return (True, str(submission_dir.relative_to(BASE_DIR)))
        except Exception:
            # 不向客户端回显内部路径等信息
            return (False, "保存提交内容时出错，请稍后重试")

    # --- 管理后台：提交记录 ---
    def list_submissions(self, status_filter=None):
        """列出提交记录（含正文、状态、是否有图片），按时间倒序"""
        submissions_dir = self.get_submissions_dir()
        if not submissions_dir.exists():
            return []
        submissions = []
        for item in submissions_dir.iterdir():
            if not item.is_dir():
                continue
            metadata_file = item / "metadata.json"
            if not metadata_file.exists():
                continue
            try:
                metadata = read_json_file(metadata_file, default=_METADATA_READ_FAILED)
                if metadata is _METADATA_READ_FAILED:
                    logger.error(f"读取提交记录失败：{item.name}（文件损坏或不可读）")
                    continue
                content_file = item / "content.txt"
                content = ""
                if content_file.exists():
                    with open(content_file, "r", encoding="utf-8") as f:
                        content = f.read()
                metadata["id"] = item.name
                metadata["content"] = content
                metadata["status"] = metadata.get("status", "unprocessed")
                metadata["has_images"] = len(metadata.get("images", [])) > 0
                if status_filter and status_filter != "all":
                    if metadata["status"] != status_filter:
                        continue
                submissions.append(metadata)
            except Exception as e:
                logger.error(f"读取提交记录失败：{item.name}, 错误：{e}")
                continue
        submissions.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return submissions

    def _resolve_submission_dir(self, submission_id):
        """
        校验并解析提交记录 ID（防目录穿越双保险）：黑名单 + resolve 后仍在根内。
        非法返回 None。
        """
        if (
            not isinstance(submission_id, str)
            or not submission_id
            or _ILLEGAL_ID_CHARS.search(submission_id)
        ):
            return None
        base = self.get_submissions_dir().resolve()
        try:
            resolved = (self.get_submissions_dir() / submission_id).resolve()
            resolved.relative_to(base)
        except (ValueError, OSError):
            return None
        return resolved

    def update_submission_status(self, submission_id, status):
        submission_dir = self._resolve_submission_dir(submission_id)
        if submission_dir is None:
            return (False, "非法的提交记录 ID")
        if not submission_dir.exists():
            return (False, "提交记录不存在")
        metadata_file = submission_dir / "metadata.json"
        if not metadata_file.exists():
            return (False, "元数据文件不存在")
        try:
            metadata = read_json_file(metadata_file, default=_METADATA_READ_FAILED)
            if metadata is _METADATA_READ_FAILED:
                return (False, "元数据文件损坏或不可读")
            metadata["status"] = status
            if not write_json_file(metadata_file, metadata, ensure_ascii=False, indent=2):
                return (False, "更新状态失败：写入失败")
            return (True, "状态更新成功")
        except Exception as e:
            return (False, f"更新状态失败：{e}")

    def delete_submission(self, submission_id):
        submission_dir = self._resolve_submission_dir(submission_id)
        if submission_dir is None:
            return (False, "非法的提交记录 ID")
        if not submission_dir.exists():
            return (False, "提交记录不存在")
        try:
            shutil.rmtree(submission_dir, ignore_errors=True)
            return (True, "删除成功")
        except Exception as e:
            return (False, f"删除失败：{e}")

    # --- 清理 ---
    def cleanup_old_submissions(self):
        """清理超过保留天数的提交目录"""
        submissions_dir = self.get_submissions_dir()
        if not submissions_dir.exists():
            return
        cutoff = datetime.now() - timedelta(days=RETENTION_DAYS)
        for item in submissions_dir.iterdir():
            if not item.is_dir():
                continue
            parts = item.name.split("_")
            if len(parts) < 3:
                continue
            try:
                item_date = datetime.strptime(parts[-3], "%Y-%m-%d")
                if item_date < cutoff:
                    shutil.rmtree(item, ignore_errors=True)
            except (ValueError, IndexError):
                continue
