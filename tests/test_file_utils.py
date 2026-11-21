"""
file_utils JSON 读写、TTL 缓存、原子写 单元测试
"""

import json
from pathlib import Path

from Module.common import file_utils


def test_read_missing_returns_default(tmp_path):
    """不存在的文件返回默认值"""
    assert file_utils.read_json_file(tmp_path / "missing.json", default={"x": 1}) == {
        "x": 1
    }


def test_write_and_read_roundtrip(tmp_path):
    """写入后可读回同一结构，且文件为 UTF-8 JSON"""
    target = tmp_path / "data.json"
    payload = {"name": "测试", "list": [1, 2]}
    assert file_utils.write_json_file(target, payload, ensure_ascii=False) is True
    assert file_utils.read_json_file(target) == payload
    raw = target.read_text(encoding="utf-8")
    assert json.loads(raw) == payload


def test_write_creates_parent_dir(tmp_path):
    """写入自动创建父目录"""
    target = tmp_path / "a" / "b" / "c.json"
    assert file_utils.write_json_file(target, {"v": 1}) is True
    assert target.exists()


def test_cached_read_returns_deepcopy(tmp_path):
    """缓存读取返回 deepcopy，修改返回值不污染缓存"""
    target = tmp_path / "c.json"
    file_utils.write_json_file(target, {"items": [1, 2]})
    first = file_utils.read_json_file_cached(target, ttl=5.0)
    first["items"].append(99)
    second = file_utils.read_json_file_cached(target, ttl=5.0)
    assert second["items"] == [1, 2]
    assert first is not second


def test_invalidate_json_cache_then_reread(tmp_path):
    """invalidate 后再次读出更新的磁盘内容"""
    target = tmp_path / "d.json"
    file_utils.write_json_file(target, {"v": 1})
    assert file_utils.read_json_file_cached(target, ttl=5.0) == {"v": 1}
    file_utils.invalidate_json_cache(target)
    file_utils.write_json_file(target, {"v": 2})
    assert file_utils.read_json_file_cached(target, ttl=5.0) == {"v": 2}
