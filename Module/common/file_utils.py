"""
文件工具模块

提供线程安全的 JSON 文件读写操作。
"""

import json
import threading
import time
import copy
import collections
from pathlib import Path

# 文件锁字典（使用 OrderedDict 实现 LRU 淘汰）
_file_locks = collections.OrderedDict()
_locks_lock = threading.Lock()
_LOCKS_MAX = 1000  # 最大锁数量


def _get_file_lock(file_path):
    """
    获取指定文件的锁（带 LRU 淘汰）

    Args:
        file_path: 文件路径

    Returns:
        threading.Lock: 文件锁
    """
    # 使用绝对路径作为锁的键
    abs_path = str(file_path.absolute())

    with _locks_lock:
        if abs_path in _file_locks:
            # 移到末尾（最近使用）
            _file_locks.move_to_end(abs_path)
            return _file_locks[abs_path]
        # 超过上限时移除最旧的锁
        if len(_file_locks) >= _LOCKS_MAX:
            _file_locks.popitem(last=False)
        lock = threading.Lock()
        _file_locks[abs_path] = lock
        return lock


def read_json_file(file_path, default=None):
    """
    线程安全地读取 JSON 文件

    Args:
        file_path: 文件路径
        default: 文件不存在或读取失败时的默认值

    Returns:
        dict or list: JSON 数据
    """
    if default is None:
        default = {}

    file_path = Path(file_path)
    lock = _get_file_lock(file_path)

    with lock:
        try:
            if not file_path.exists():
                return default
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return default
        except json.JSONDecodeError as e:
            import structlog

            logger = structlog.get_logger(__name__)
            logger.error("json_parse_error", file_path=str(file_path), error=str(e))
            return default


def write_json_file(file_path, data, ensure_ascii=False, indent=2):
    """
    线程安全地写入 JSON 文件

    Args:
        file_path: 文件路径
        data: 要写入的数据
        ensure_ascii: 是否确保 ASCII 编码
        indent: 缩进空格数

    Returns:
        bool: 写入成功返回 True，失败返回 False
    """
    file_path = Path(file_path)
    lock = _get_file_lock(file_path)

    with lock:
        # 临时文件路径在 try 前确定：确保异常清理分支引用时必然已赋值（bug #22）
        temp_path = file_path.with_suffix(".tmp")
        try:
            # 确保目录存在
            file_path.parent.mkdir(parents=True, exist_ok=True)

            # 符号链接检查：防止通过 symlink 写入任意文件
            if file_path.exists() and file_path.is_symlink():
                import structlog

                structlog.get_logger(__name__).warning(
                    "symlink_detected", path=str(file_path)
                )
                return False

            # 原子写入：先写入临时文件，然后重命名
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=ensure_ascii, indent=indent)

            # 重命名临时文件为目标文件（原子操作）
            temp_path.replace(file_path)
            # 写入后使缓存失效，保证下次读取为最新数据
            invalidate_json_cache(file_path)
            return True
        except Exception:
            # 清理临时文件（unlink 仅抛 OSError 系异常，收窄裸 except，bug #22）
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass
            return False


# TTL 缓存：绝对路径 -> (过期时间戳, 数据)
_json_cache = {}
_json_cache_lock = threading.Lock()
_JSON_CACHE_MAX = 1000  # 缓存上限，防止无界增长


def read_json_file_cached(file_path, default=None, ttl=5.0):
    """
    线程安全地读取 JSON 文件（带 TTL 缓存）

    命中缓存时返回 deepcopy，避免调用方修改污染缓存。

    Args:
        file_path: 文件路径
        default: 文件不存在或读取失败时的默认值
        ttl: 缓存有效期（秒），默认 5 秒

    Returns:
        dict or list: JSON 数据
    """
    if default is None:
        default = {}

    file_path = Path(file_path)
    key = str(file_path.absolute())
    now = time.time()

    with _json_cache_lock:
        entry = _json_cache.get(key)
        if entry and now - entry[0] < ttl:
            return copy.deepcopy(entry[1])

    data = read_json_file(file_path, default)
    with _json_cache_lock:
        # 缓存有界：超过上限时整体清空，避免无界增长
        if len(_json_cache) >= _JSON_CACHE_MAX:
            _json_cache.clear()
        _json_cache[key] = (now, data)
    return copy.deepcopy(data)


def invalidate_json_cache(file_path):
    """
    使指定文件的缓存立即失效（写入后由 write_json_file 自动调用）
    """
    key = str(Path(file_path).absolute())
    with _json_cache_lock:
        _json_cache.pop(key, None)
