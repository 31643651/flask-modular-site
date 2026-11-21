"""
画廊偏好/收藏读-改-写互斥保护测试（bug #27）

- 偏好：并发 10 线程各保存不同用户后，文件包含全部更新、无丢写
  （save_user_preferences 的 load→改→write 整体持锁；无锁时先写者会被后写者的
  整文件覆盖抹掉）
- 收藏：并发全量替换（DELETE+INSERT）后表状态始终为某个完整快照，无交错半成品
"""

import threading

import pytest

from Module.core.gallery_service import GalleryService


@pytest.fixture
def prefs_file(tmp_path, monkeypatch):
    """将画廊偏好 JSON 重定向到临时文件，避免写生产 gallery_preferences.json"""
    target = tmp_path / "gallery_preferences.json"
    monkeypatch.setattr("Module.core.gallery_service.PREFERENCES_FILE", target)
    return target


class TestConcurrentPreferenceSaves:
    """save_user_preferences 读-改-写整体持锁（bug #27 主修复）"""

    def test_ten_threads_different_users_all_present(self, prefs_file):
        """并发 10 线程各写不同用户：文件包含全部 10 个用户、无丢写"""
        service = GalleryService()
        barrier = threading.Barrier(10)
        errors = []

        def worker(i):
            try:
                barrier.wait()
                ok = service.save_user_preferences(
                    f"user{i}", {"discover_format": f"fmt{i}"}
                )
                if ok is not True:
                    errors.append(f"thread {i}: save returned {ok}")
            except Exception as e:  # 线程内异常收集后统一断言
                errors.append(f"thread {i}: {e!r}")

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []

        final = service.load_preferences()
        users = final["users"]
        assert len(users) == 10
        for i in range(10):
            assert users[f"user{i}"]["discover_format"] == f"fmt{i}"

    def test_sequential_saves_merge_not_overwrite(self, prefs_file):
        """顺序保存不同用户为合并语义（既有行为不回归）"""
        service = GalleryService()
        assert service.save_user_preferences("a", {"k": "v1"}) is True
        assert service.save_user_preferences("b", {"k": "v2"}) is True

        final = service.load_preferences()
        assert final["users"]["a"]["k"] == "v1"
        assert final["users"]["b"]["k"] == "v2"


class TestConcurrentFavoritesSaves:
    """save_favorites 全量替换持锁（bug #27）"""

    def test_concurrent_full_replaces_end_in_complete_snapshot(self, switch_db):
        """并发全量替换后，表状态必为某一个完整输入快照（无交错/半成品）"""
        service = GalleryService()
        service.save_favorites({"seed": ["p0"]})

        n = 8
        barrier = threading.Barrier(n)
        errors = []

        def worker(i):
            try:
                barrier.wait()
                service.save_favorites({f"user{i}": [f"path{i}"]})
            except Exception as e:
                errors.append(f"thread {i}: {e!r}")

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []

        favorites = service.load_favorites()
        # 最终状态必是某个线程的完整快照：恰好一个用户名及其对应路径
        assert len(favorites) == 1
        (username, paths), = favorites.items()
        assert username.startswith("user")
        assert paths == [f"path{username[len('user'):]}"]

    def test_save_load_roundtrip(self, switch_db):
        """收藏保存后读回一致（既有行为不回归）"""
        service = GalleryService()
        service.save_favorites({"alice": ["a.jpg", "b.jpg"], "bob": ["c.jpg"]})

        favorites = service.load_favorites()
        assert favorites == {"alice": ["a.jpg", "b.jpg"], "bob": ["c.jpg"]}
