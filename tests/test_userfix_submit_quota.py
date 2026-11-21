"""
userfix 提交配额扣减时序测试（bug #18）：

- 校验失败路径（空文本 / 超长文本 / 图片数量超限）不再扣减当日配额
- 成功提交后配额 +1
- 当日配额用尽后成功参数的提交被拒绝且配额不变、不落盘
"""

import io

import pytest

from Module.common import user_utils
from Module.userfix import userfix as userfix_module

CSRF_TOKEN = "test-csrf-token"

USERNAME = "bob"


def _png_bytes():
    """最小可用 PNG 字节（仅作为上传载荷，不做图像校验）"""
    return b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


def _png_files(count, name_prefix="img"):
    """构造 count 个 multipart 文件字段"""
    return [
        (f"images", (io.BytesIO(_png_bytes()), f"{name_prefix}_{i}.png"))
        for i in range(1, count + 1)
    ]


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
        sess["csrf_token"] = CSRF_TOKEN


# Flask 测试客户端默认 UA 会被 ipguard 判为 Other 并触发第一防线限流，
# 统一携带真实浏览器 UA 规避与被测逻辑无关的拦截
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


def _post(client, text="", images=None):
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
    """将 BASE_DIR、配额文件与提交目录重定向到临时位置，避免触碰生产数据。

    save_submission 成功时通过 relative_to(BASE_DIR) 计算展示路径，
    因此 BASE_DIR 也必须随提交目录一起重定向。
    """
    monkeypatch.setattr("Module.core.userfix_service.BASE_DIR", tmp_path)
    limits_file = tmp_path / "userfix_limits.json"
    submissions_dir = tmp_path / "submissions"
    monkeypatch.setattr("Module.core.userfix_service.USERFIX_LIMITS_FILE", limits_file)
    monkeypatch.setattr("Module.core.userfix_service.USERFIX_SUBMISSIONS_DIR", submissions_dir)
    return {"limits_file": limits_file, "submissions_dir": submissions_dir}


class TestQuotaNotConsumedOnFailure:
    """校验失败路径不扣配额（bug #18 主修复）"""

    def test_empty_text_keeps_quota(self, client, app, userfix_env):
        """空文本提交被拒且配额计数不变"""
        _login_user(client)
        assert _count() == 0

        resp = _post(client, text="")

        assert resp.status_code == 200
        assert resp.get_json()["success"] is False
        assert _count() == 0
        assert not userfix_env["submissions_dir"].exists()

    def test_whitespace_text_keeps_quota(self, client, app, userfix_env):
        """纯空白文本（strip 后为空）同样不扣配额"""
        _login_user(client)

        resp = _post(client, text="   \n\t  ")

        assert resp.get_json()["success"] is False
        assert _count() == 0

    def test_oversized_text_keeps_quota(self, client, app, userfix_env):
        """超长文本（>10000 字符）被拒且配额不变"""
        _login_user(client)

        resp = _post(client, text="a" * 10001)

        assert resp.get_json()["success"] is False
        assert _count() == 0

    def test_too_many_images_keeps_quota(self, client, app, userfix_env):
        """图片数量超限（>6 张）被拒且配额不变"""
        _login_user(client)

        resp = _post(client, text="内容", images=_png_files(7))

        assert resp.get_json()["success"] is False
        assert _count() == 0
        assert not userfix_env["submissions_dir"].exists()

    def test_oversized_image_keeps_quota(self, client, app, userfix_env):
        """单图大小超限（>5MB）被拒且配额不变（bug #18 修复轮 1：前置校验）"""
        _login_user(client)
        oversized = b"\x00" * (5 * 1024 * 1024 + 1)

        resp = _post(
            client,
            text="内容",
            images=[("images", (io.BytesIO(oversized), "big.png"))],
        )

        data = resp.get_json()
        assert data["success"] is False
        assert "图片大小超出限制" in data["message"]
        # 配额未扣减（校验发生在 check_and_increment_submission 之前）
        assert _count() == 0
        assert not userfix_env["submissions_dir"].exists()

    def test_image_at_size_limit_passes(self, client, app, userfix_env):
        """恰好 5MB 的图片不触发大小拒绝，正常提交并扣配额 +1
        （ADR-0008 适配：payload 以真实 PNG 头开头，内容需通过 magic-bytes 校验；
        断言强度不变——仍验证 5MB 整数值不被大小拒绝）"""
        _login_user(client)
        at_limit = b"\x89PNG\r\n\x1a\n" + b"\x00" * (5 * 1024 * 1024 - 8)
        assert len(at_limit) == 5 * 1024 * 1024

        resp = _post(
            client,
            text="内容",
            images=[("images", (io.BytesIO(at_limit), "edge.png"))],
        )

        data = resp.get_json()
        assert data["success"] is True
        assert _count() == 1


class TestQuotaConsumedOnSuccess:
    """成功路径配额判断与递增仍然完整"""

    def test_successful_submission_increments_quota_once(
        self, client, app, userfix_env
    ):
        """成功提交后配额恰好 +1"""
        _login_user(client)

        resp = _post(client, text="有效反馈", images=_png_files(1))

        assert resp.get_json()["success"] is True
        assert _count() == 1
        # 提交内容确实落盘
        assert userfix_env["submissions_dir"].exists()
        assert len(list(userfix_env["submissions_dir"].iterdir())) == 1

    def test_three_successes_then_rejected(self, client, app, userfix_env):
        """连续成功 3 次用尽当日配额后，第 4 次成功参数的提交被拒绝"""
        _login_user(client)

        for i in range(3):
            resp = _post(client, text=f"反馈 {i}")
            assert resp.get_json()["success"] is True
        assert _count() == 3

        resp = _post(client, text="第 4 次")
        data = resp.get_json()
        assert data["success"] is False
        assert "已用完" in data["message"]
        assert _count() == 3
        assert len(list(userfix_env["submissions_dir"].iterdir())) == 3

    def test_quota_exhausted_valid_submission_rejected_no_disk_write(
        self, client, app, userfix_env
    ):
        """预置配额已用尽：合法参数提交被拒且配额不变、不产生提交目录"""
        _login_user(client)
        today = userfix_module.get_today_date()
        userfix_module.save_limits({today: {USERNAME: 3}})
        assert _count() == 3

        resp = _post(client, text="合法内容", images=_png_files(1))

        data = resp.get_json()
        assert data["success"] is False
        assert "已用完" in data["message"]
        assert _count() == 3
        assert (
            not userfix_env["submissions_dir"].exists()
            or list(userfix_env["submissions_dir"].iterdir()) == []
        )
