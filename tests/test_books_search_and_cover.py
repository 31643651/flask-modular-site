"""
书籍模块测试：搜索翻页链接 urlencode（bug #9）与封面子目录路由（bug #10）

- 翻页链接：含 & + 空格 / 中文的关键词在分页链接中被正确编码，可还原
- 封面路由：/book/static/<path:filename> 支持子目录封面，目录穿越被拒
"""

import re
import json
import urllib.parse

import pytest

from Module.common import db_utils

# 测试客户端默认 UA 会被 ipguard 第一防线判定为异常 UA（阈值 3 次/分钟），
# books 测试请求次数多，统一携带真实浏览器 UA 规避 ipguard 干扰（其本身非被测对象）
BROWSER_UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


def _get(client, path, **kwargs):
    """带浏览器 UA 的 GET 请求"""
    headers = kwargs.pop("headers", {})
    return client.get(path, headers={**BROWSER_UA, **headers}, **kwargs)


@pytest.fixture
def book_env(tmp_path, monkeypatch, switch_db):
    """
    临时书籍环境：
    - 临时封面根目录（含中文子目录与特殊字符文件名）
    - 临时书籍数据目录（保证路径存在，搜索路由可进入正常分支）
    - 临时 config.json 并 monkeypatch 到 books 模块（CONFIG_FILE 在 books.py 内具名导入）
    - 临时 SQLite（switch_db）写入书籍数据并清空 books 模块 TTL 缓存
    """
    static_root = tmp_path / "book_static"
    sub = static_root / "封面"
    sub.mkdir(parents=True)
    (static_root / "top.jpg").write_bytes(b"top-jpeg")
    (sub / "cover.jpg").write_bytes(b"sub-jpeg")
    (sub / "my pic #1.jpg").write_bytes(b"special-jpeg")

    data_root = tmp_path / "book_data"
    data_root.mkdir()

    config_file = tmp_path / "config.json"
    config_file.write_text(
        json.dumps(
            {
                "paths": {
                    "book_data_path": str(data_root),
                    "book_static_path": str(static_root),
                }
            }
        ),
        encoding="utf-8",
    )
    # 临时 config.json 并 monkeypatch 到 config_utils（BooksService 统一经 config_utils 读取）
    monkeypatch.setattr("Module.common.config_utils.CONFIG_FILE", config_file)

    # 清空服务层缓存，确保读到临时库数据
    monkeypatch.setattr("Module.core.books_service._books_cache", None)
    monkeypatch.setattr("Module.core.books_service._books_cache_ts", 0.0)

    con = db_utils.get_connection()
    con.execute(
        "INSERT INTO books (id, title, author, description, detail, cover) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (1, "魔法书", "作者 a&b+c d 魔法", "描述A", "详情A", "封面/cover.jpg"),
    )
    con.execute(
        "INSERT INTO books (id, title, author, description, detail, cover) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (2, "魔法书", "作者 a&b+c d 魔法", "描述B", "详情B", "封面/my pic #1.jpg"),
    )
    con.execute(
        "INSERT INTO books (id, title, author, description, detail, cover) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (3, "魔法书", "作者 a&b+c d 魔法", "描述C", "详情C", "top.jpg"),
    )
    con.commit()
    con.close()

    yield {"static_root": static_root}


def _login(client, app, username="alice"):
    """注入登录态（全局认证中间件要求）"""
    from Module.common import user_utils

    user_utils.save_users(
        {
            username: {
                "id": 1,
                "username": username,
                "password": "pass123",
                "role": "user",
                "enabled": True,
            },
        }
    )
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["username"] = username
        sess["role"] = "user"
        sess["verified"] = True


def _extract_pagination_hrefs(html):
    """从渲染结果提取全部分页链接中的 q 与 page"""
    pairs = re.findall(r'href="/book/search\?q=([^"&]+)&page=(\d+)"', html)
    assert pairs, "渲染结果中未找到分页链接"
    return pairs


class TestPaginationLinksEncoded:
    """bug #9：翻页链接中 search_term 必须正确编码"""

    def test_special_chars_round_trip(self, client, app, book_env):
        """含 & + 空格的关键词：翻页链接编码后可完整还原"""
        _login(client, app)
        term = "a&b+c d"
        resp = _get(client, "/book/search", query_string={"q": term, "per_page": 1})
        assert resp.status_code == 200
        pairs = _extract_pagination_hrefs(resp.get_data(as_text=True))
        for encoded_q, page in pairs:
            # q 值内部不得出现未编码的裸特殊字符
            assert urllib.parse.unquote(encoded_q) == term
            assert encoded_q.endswith("%20d")
        # 至少包含上一页/下一页链接（共 3 页）
        assert any(page in ("1", "2", "3") for _, page in pairs)

    def test_chinese_term_round_trip(self, client, app, book_env):
        """中文关键词：翻页链接以 UTF-8 百分号编码，还原后与原词一致"""
        _login(client, app)
        term = "魔法"
        resp = _get(client, "/book/search", query_string={"q": term, "per_page": 1})
        assert resp.status_code == 200
        for encoded_q, _ in _extract_pagination_hrefs(resp.get_data(as_text=True)):
            assert urllib.parse.unquote(encoded_q) == term

    def test_encoded_links_reachable(self, client, app, book_env):
        """按渲染出的编码链接原样请求，搜索条件在翻页后保持"""
        _login(client, app)
        term = "a&b+c d"
        resp = _get(client, "/book/search", query_string={"q": term, "per_page": 1})
        hrefs = _extract_pagination_hrefs(resp.get_data(as_text=True))
        q_value, page_value = hrefs[0]
        # 原样使用渲染出的 q 值拼链接（模拟浏览器行为）
        follow = _get(
            client,
            f"/book/search?q={q_value}&page={page_value}&per_page=1",
        )
        assert follow.status_code == 200
        assert "第 2/3 页" in follow.get_data(as_text=True)


class TestCoverRoute:
    """bug #10：封面路由支持子目录并拒绝目录穿越"""

    def test_top_level_cover_200(self, client, app, book_env):
        """顶层封面仍可访问（无回归）"""
        _login(client, app)
        resp = _get(client, "/book/static/top.jpg")
        assert resp.status_code == 200
        assert resp.mimetype == "image/jpeg"

    def test_subdirectory_cover_200(self, client, app, book_env):
        """中文子目录封面可访问（path 转换器）"""
        _login(client, app)
        resp = _get(client, "/book/static/" + urllib.parse.quote("封面/cover.jpg"))
        assert resp.status_code == 200
        assert resp.mimetype == "image/jpeg"

    def test_space_and_hash_filename_200(self, client, app, book_env):
        """含空格与 # 的子目录封面：URL 编码后可正确解码访问"""
        _login(client, app)
        cover = "封面/my pic #1.jpg"
        resp = _get(client, "/book/static/" + urllib.parse.quote(cover))
        assert resp.status_code == 200
        assert resp.mimetype == "image/jpeg"

    def test_template_cover_url_reachable(self, client, app, book_env):
        """搜索页渲染的封面 URL（模板 urlencode 后）可直接访问"""
        _login(client, app)
        resp = _get(client, "/book/search")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        srcs = re.findall(r'src="/book/static/([^"]+)"', html)
        assert srcs, "搜索页未渲染任何封面 URL"
        for encoded_cover in srcs:
            cover_resp = _get(client, f"/book/static/{encoded_cover}")
            assert cover_resp.status_code == 200

    def test_traversal_rejected(self, client, app, book_env):
        """../ 目录穿越被拒（404），不得泄漏封面根目录之外的文件"""
        _login(client, app)
        for path in (
            "/book/static/../../Module/common/paths.py",
            "/book/static/..%2F..%2Fcommon%2Fpaths.py",
            "/book/static/%2e%2e/%2e%2e/common/paths.py",
        ):
            resp = _get(client, path)
            assert resp.status_code == 404, f"{path} 未被拒绝"

    def test_missing_cover_404(self, client, app, book_env):
        """不存在的封面返回 404"""
        _login(client, app)
        resp = _get(client, "/book/static/" + urllib.parse.quote("封面/nope.jpg"))
        assert resp.status_code == 404
