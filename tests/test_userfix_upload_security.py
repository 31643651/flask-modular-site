"""
反馈上传图片安全加固测试（ADR-0008）

三层修复的行为锚定：
1. 非白名单扩展名上传被拒绝且不扣配额、不落盘（不再改名 .jpg 保存）
2. magic-bytes 与扩展名不符的上传被拒绝且不扣配额（顶着 .jpg 的 SVG/HTML 等）
3. serve_image：白名单扩展返回固定 MIME；非白名单扩展 404；
   内容与扩展名不符（历史被改名存为 .jpg 的脏文件）404
"""

import io

import pytest

from Module.common import user_utils
from Module.userfix import userfix as userfix_module

CSRF_TOKEN = "test-csrf-token"
USERNAME = "bob"

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

PNG_HEAD = b"\x89PNG\r\n\x1a\n"
SVG_BYTES = b"<svg xmlns='http://www.w3.org/2000/svg'></svg>"
HTML_BYTES = b"<html><script>alert(1)</script></html>"


def _png_bytes():
    """最小可用 PNG 头（含 magic-bytes，供过校验的正常上传使用）"""
    return PNG_HEAD + b"\x00" * 16


def _login_user(client):
    """以普通用户身份伪造会话（绕过登录页，直接注入 session）"""
    user_utils.save_users(
        {
            USERNAME: {
                "id": 2,
                "username": USERNAME,
                "password": "p",
                "role": "user",
                "enabled": True,
            }
        }
    )
    with client.session_transaction() as sess:
        sess["user_id"] = 2
        sess["username"] = USERNAME
        sess["role"] = "user"
        sess["verified"] = False
        sess["csrf_token"] = CSRF_TOKEN


def _post(client, text="内容", images=None):
    data = {"text": text}
    for field, (stream, filename) in (images or []):
        data.setdefault(field, [])
        data[field].append((stream, filename))
    return client.post(
        "/userfix/submit",
        data=data,
        headers={"X-CSRF-Token": CSRF_TOKEN, "User-Agent": BROWSER_UA},
    )


def _count():
    return userfix_module.get_user_submission_count(USERNAME)


@pytest.fixture
def userfix_env(tmp_path, monkeypatch):
    """将 BASE_DIR、配额文件与提交目录重定向到临时位置，避免触碰生产数据"""
    monkeypatch.setattr("Module.core.userfix_service.BASE_DIR", tmp_path)
    limits_file = tmp_path / "userfix_limits.json"
    submissions_dir = tmp_path / "submissions"
    monkeypatch.setattr("Module.core.userfix_service.USERFIX_LIMITS_FILE", limits_file)
    monkeypatch.setattr("Module.core.userfix_service.USERFIX_SUBMISSIONS_DIR", submissions_dir)
    return {"limits_file": limits_file, "submissions_dir": submissions_dir}


class TestUploadWhitelistRejected:
    """缺陷 1：非白名单扩展被拒绝而非改名 .jpg 保存"""

    def test_svg_extension_rejected_no_quota(self, client, app, userfix_env):
        """.svg 上传被拒绝，不扣配额、不落盘"""
        _login_user(client)
        resp = _post(
            client,
            text="内容",
            images=[("images", (io.BytesIO(SVG_BYTES), "evil.svg"))],
        )

        data = resp.get_json()
        assert data["success"] is False
        assert "不支持的图片格式" in data["message"]
        assert _count() == 0
        assert not userfix_env["submissions_dir"].exists()

    def test_html_extension_rejected_no_quota(self, client, app, userfix_env):
        """.html 上传被拒绝，不扣配额、不落盘"""
        _login_user(client)
        resp = _post(
            client,
            text="内容",
            images=[("images", (io.BytesIO(HTML_BYTES), "evil.html"))],
        )

        data = resp.get_json()
        assert data["success"] is False
        assert "不支持的图片格式" in data["message"]
        assert _count() == 0
        assert not userfix_env["submissions_dir"].exists()

    def test_no_extension_rejected_no_quota(self, client, app, userfix_env):
        """无扩展名文件被拒绝（即便内容是合法 PNG）"""
        _login_user(client)
        resp = _post(
            client,
            text="内容",
            images=[("images", (io.BytesIO(_png_bytes()), "payload"))],
        )

        data = resp.get_json()
        assert data["success"] is False
        assert "不支持的图片格式" in data["message"]
        assert _count() == 0
        assert not userfix_env["submissions_dir"].exists()

    def test_uppercase_whitelist_extension_accepted(self, client, app, userfix_env):
        """.PNG（大写白名单扩展）与合法内容正常通过"""
        _login_user(client)
        resp = _post(
            client,
            text="内容",
            images=[("images", (io.BytesIO(_png_bytes()), "PIC.PNG"))],
        )

        assert resp.get_json()["success"] is True
        assert _count() == 1


class TestUploadMagicRejected:
    """缺陷 2：magic-bytes 与扩展名不符被拒绝"""

    def test_svg_content_as_jpg_rejected_no_quota(self, client, app, userfix_env):
        """SVG 内容顶着 .jpg 被拒绝，不扣配额、不落盘（探针实测的 479KB 场景）"""
        _login_user(client)
        resp = _post(
            client,
            text="内容",
            images=[("images", (io.BytesIO(SVG_BYTES), "pic.jpg"))],
        )

        data = resp.get_json()
        assert data["success"] is False
        assert "扩展名不符" in data["message"]
        assert _count() == 0
        assert not userfix_env["submissions_dir"].exists()

    def test_html_content_as_png_rejected_no_quota(self, client, app, userfix_env):
        """HTML 内容顶着 .png 被拒绝，不扣配额、不落盘"""
        _login_user(client)
        resp = _post(
            client,
            text="内容",
            images=[("images", (io.BytesIO(HTML_BYTES), "shot.png"))],
        )

        data = resp.get_json()
        assert data["success"] is False
        assert "扩展名不符" in data["message"]
        assert _count() == 0
        assert not userfix_env["submissions_dir"].exists()

    def test_short_payload_rejected(self, client, app, userfix_env):
        """过短文件（不足 magic 长度）被拒绝"""
        _login_user(client)
        resp = _post(
            client,
            text="内容",
            images=[("images", (io.BytesIO(b"\x89PN"), "tiny.png"))],
        )

        data = resp.get_json()
        assert data["success"] is False
        assert "扩展名不符" in data["message"]
        assert _count() == 0

    def test_valid_png_accepted_control(self, client, app, userfix_env):
        """对照组：合法 PNG 正常提交并扣配额"""
        _login_user(client)
        resp = _post(
            client,
            text="内容",
            images=[("images", (io.BytesIO(_png_bytes()), "ok.png"))],
        )

        assert resp.get_json()["success"] is True
        assert _count() == 1
        assert userfix_env["submissions_dir"].exists()


class TestServeImageHardening:
    """缺陷 3：serve_image 显式 MIME + 白名单 404 + 内容校验 404"""

    @pytest.fixture
    def seeded_root(self, tmp_path, monkeypatch):
        """将图片服务根目录重定向到临时位置（serve 运行时读取服务模块属性）"""
        monkeypatch.setattr("Module.core.userfix_service.BASE_DIR", tmp_path)
        submissions = tmp_path / "Module" / "userfix" / "submissions"
        monkeypatch.setattr(
            "Module.core.userfix_service.USERFIX_SUBMISSIONS_DIR", submissions
        )
        sub = submissions / "alice_2026-01-01_00-00-00_000000"
        sub.mkdir(parents=True)
        return sub

    @staticmethod
    def _get(client, submission_dir, filename):
        return client.get(
            f"/userfix/image/{submission_dir.name}/{filename}",
            headers={"User-Agent": BROWSER_UA},
        )

    @pytest.mark.parametrize(
        "filename, content, expected_mime",
        [
            ("a.png", PNG_HEAD + b"\x00" * 8, "image/png"),
            ("b.jpg", b"\xff\xd8\xff\xe0" + b"\x00" * 12, "image/jpeg"),
            ("c.jpeg", b"\xff\xd8\xff" + b"\x00" * 12, "image/jpeg"),
            ("d.gif", b"GIF89a" + b"\x00" * 8, "image/gif"),
            ("e.webp", b"RIFF" + b"\x00" * 4 + b"WEBP" + b"\x00" * 8, "image/webp"),
            ("f.bmp", b"BM" + b"\x00" * 12, "image/bmp"),
        ],
    )
    def test_whitelist_extension_explicit_mime(
        self, client, app, seeded_root, filename, content, expected_mime
    ):
        """白名单扩展返回固定 MIME（显式传入，不依赖 mimetypes 猜测）"""
        _login_user(client)
        (seeded_root / filename).write_bytes(content)

        resp = self._get(client, seeded_root, filename)

        assert resp.status_code == 200
        assert resp.mimetype == expected_mime

    def test_non_whitelist_extension_404(self, client, app, seeded_root):
        """非白名单扩展（.svg）即使文件存在也 404，不服务"""
        _login_user(client)
        (seeded_root / "evil.svg").write_bytes(SVG_BYTES)

        resp = self._get(client, seeded_root, "evil.svg")

        assert resp.status_code == 404

    def test_mismatched_content_404(self, client, app, seeded_root):
        """历史被改名存为 .png 的非位图脏文件：内容校验 404，服务层闭环"""
        _login_user(client)
        (seeded_root / "legacy.png").write_bytes(SVG_BYTES)

        resp = self._get(client, seeded_root, "legacy.png")

        assert resp.status_code == 404

    def test_missing_file_still_404(self, client, app, seeded_root):
        """不存在的文件仍 404（基线回归）"""
        _login_user(client)
        resp = self._get(client, seeded_root, "nope.png")
        assert resp.status_code == 404
