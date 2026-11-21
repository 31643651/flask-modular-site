"""
画廊 browse/folder_images 目录穿越加固测试（bug #19）：

- `..` 段（原始 / URL 编码 ../ ..%2f / %2e%2e / 反斜杠）被拒，返回 404
- Windows 绝对/根化形态（C:/xxx、C:xxx、%2f 开头）被拒，返回 404
- 拒绝响应不泄露根外任何目录/文件名
- 合法子路径（含嵌套、中文、空格名）行为完全不变
- serve_image 既有 relative_to 校验不被削弱（回归确认 403）
"""

from urllib.parse import quote
import json

import pytest

from Module.common import user_utils


@pytest.fixture
def gallery_root(tmp_path, monkeypatch):
    """构造临时画廊根目录，并把 config.json 重定向到临时文件"""
    root = tmp_path / "gallery_root"
    root.mkdir()
    config_file = tmp_path / "config.json"
    config_file.write_text(
        json.dumps({"paths": {"gallery_root_path": str(root)}}),
        encoding="utf-8",
    )
    monkeypatch.setattr("Module.common.config_utils.CONFIG_FILE", config_file)
    return root


@pytest.fixture
def logged_in(client, app):
    """创建用户并注入登录态"""
    user_utils.save_users(
        {
            "alice": {
                "id": 1,
                "username": "alice",
                "password": "pass123",
                "role": "user",
                "enabled": True,
            },
        }
    )
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["username"] = "alice"
        sess["role"] = "user"
        sess["verified"] = True


@pytest.fixture
def seeded_gallery(gallery_root, logged_in):
    """根内合法目录（含嵌套/中文/空格名）与根外秘密目录（穿越目标）；依赖 logged_in 保持登录态"""
    sub = gallery_root / "vacation"
    (sub / "album").mkdir(parents=True)
    (sub / "a.jpg").write_bytes(b"fake-image-a")
    (sub / "album" / "b.jpg").write_bytes(b"fake-image-b")

    cn = gallery_root / "我的 旅行"
    cn.mkdir()
    (cn / "c.jpg").write_bytes(b"fake-image-c")

    # 根外秘密目录：穿越成功即泄露其内容
    outside = gallery_root.parent / "evil"
    outside.mkdir()
    (outside / "secret_list.txt").write_text("top secret list", encoding="utf-8")
    (outside / "sub_secret").mkdir()
    (outside / "sub_secret" / "secret_deep.txt").write_text("deep", encoding="utf-8")
    return gallery_root


# 对抗样本：原始 .. / URL 编码 ../ ..%2f / %2e%2e / 多级 / 反斜杠 / Windows 绝对路径
ADVERSARIAL_PATHS = [
    "../evil",
    "..%2fevil",
    "%2e%2e%2fevil",
    "..%2f..%2fevil",
    "%2e%2e/%2e%2e/evil",
    "..\\evil",
    "..%5cevil",
    "C:/Windows",
    "C:%2fWindows",
    "C:Windows",
    "%2e%2e%5c%2e%2e%5c%2e%2e%5cevil",
]

LEAK_MARKERS = ["secret", "top secret", "sub_secret", "Windows", "evil"]


def _assert_no_leak(body):
    for marker in LEAK_MARKERS:
        assert marker not in body


class TestBrowseTraversal:
    """browse：.. 段与绝对路径形态全部 404，且无信息泄露"""

    @pytest.mark.parametrize("evil", ADVERSARIAL_PATHS)
    def test_browse_rejects_traversal(self, client, app, seeded_gallery, evil):
        resp = client.get("/gallery/" + evil, follow_redirects=False)

        assert resp.status_code == 404
        _assert_no_leak(resp.get_data(as_text=True))

    def test_browse_rejects_encoded_outside_listing(self, client, app, seeded_gallery):
        """深度编码穿越到根外秘密目录：404 且不出现 secret_list 内容"""
        resp = client.get(
            "/gallery/" + quote("../evil/sub_secret"), follow_redirects=False
        )

        assert resp.status_code == 404
        _assert_no_leak(resp.get_data(as_text=True))


class TestFolderImagesTraversal:
    """folder_images：同样覆盖 .. 段与绝对路径形态"""

    @pytest.mark.parametrize("evil", ADVERSARIAL_PATHS)
    def test_folder_images_rejects_traversal(self, client, app, seeded_gallery, evil):
        resp = client.get("/gallery/api/folder-images/" + evil, follow_redirects=False)

        assert resp.status_code == 404
        _assert_no_leak(resp.get_data(as_text=True))

    def test_folder_images_rejects_encoded_outside_listing(
        self, client, app, seeded_gallery
    ):
        """深度编码穿越：404 且 JSON 中不含根外任何文件名"""
        resp = client.get(
            "/gallery/api/folder-images/" + quote("../evil/sub_secret"),
            follow_redirects=False,
        )

        assert resp.status_code == 404
        _assert_no_leak(resp.get_data(as_text=True))

    def test_leading_encoded_slash_never_leaks_outside(
        self, client, app, seeded_gallery
    ):
        """%2f 开头形态：测试客户端会把 %2F 解码为字面斜杠，URL 结构随之改变
        （可能落入 browse 的目录不存在页，200 空画廊页）——无论走哪条路由，
        都不得出现根外任何目录/文件名"""
        for url in (
            "/gallery/%2fWindows",
            "/gallery/api/folder-images/%2fWindows",
        ):
            resp = client.get(url, follow_redirects=False)
            assert resp.status_code in (200, 308, 404)
            _assert_no_leak(resp.get_data(as_text=True))


class TestServeImageNotWeakened:
    """serve_image 既有 relative_to 校验保持生效（回归确认，不得削弱）"""

    def test_traversal_still_403(self, client, app, seeded_gallery):
        resp = client.get("/gallery/image/..%2fsecret.txt", follow_redirects=False)
        assert resp.status_code in (403, 404)
        _assert_no_leak(resp.get_data(as_text=True))

    def test_encoded_deep_traversal_blocked(self, client, app, seeded_gallery):
        resp = client.get(
            "/gallery/image/" + quote("../evil/secret_list.txt"),
            follow_redirects=False,
        )
        assert resp.status_code in (403, 404)
        body = resp.get_data(as_text=True)
        _assert_no_leak(body)
        assert "top secret list" not in body


class TestLegitBehaviorUnchanged:
    """合法子路径行为完全不变（正常浏览 / 嵌套 / 中文空格名）"""

    def test_browse_legit_subfolder(self, client, app, seeded_gallery):
        resp = client.get("/gallery/vacation")

        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "vacation" in body
        assert "a.jpg" in body
        _assert_no_leak(body)

    def test_browse_nested_legit(self, client, app, seeded_gallery):
        """嵌套子目录（搜索/翻页跳转的常见形态）不受影响"""
        resp = client.get("/gallery/vacation/album")

        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "album" in body
        assert "b.jpg" in body
        _assert_no_leak(body)

    def test_browse_chinese_and_space_name(self, client, app, seeded_gallery):
        """中文 + 空格目录名正常浏览"""
        resp = client.get("/gallery/" + quote("我的 旅行"))

        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "我的 旅行" in body
        assert "c.jpg" in body
        _assert_no_leak(body)

    def test_folder_images_legit_recursive(self, client, app, seeded_gallery):
        resp = client.get("/gallery/api/folder-images/vacation")

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        urls = data["images"]
        assert len(urls) == 2
        assert all(u.startswith("/gallery/image/") for u in urls)
        assert any("b.jpg" in u for u in urls)
        # 绝不包含根外内容
        assert all("secret" not in u for u in urls)

    def test_folder_images_chinese_name(self, client, app, seeded_gallery):
        resp = client.get("/gallery/api/folder-images/" + quote("我的 旅行"))

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert any("c.jpg" in u for u in data["images"])
