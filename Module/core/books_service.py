"""
书籍管理业务逻辑服务

从 books.py 提取的业务逻辑：书籍加载、搜索、路径管理。
"""

import re
import threading
import time
from pathlib import Path

from Module.common.paths import BASE_DIR, CONFIG_FILE
from Module.common.file_utils import (
    read_json_file,
    write_json_file,
    read_json_file_cached,
)
from Module.common.db_utils import query

_books_cache = None
_books_cache_ts = 0.0
_books_cache_lock = threading.Lock()
_BOOKS_CACHE_TTL = 30


class BooksService:
    """书籍服务，支持依赖注入"""

    def __init__(self, db_utils=None, file_utils=None, config_utils=None):
        self.db = db_utils or __import__("Module.common.db_utils", fromlist=["query"])
        self.file_utils = file_utils or __import__(
            "Module.common.file_utils", fromlist=["read_json_file"]
        )
        self.config_utils = config_utils or __import__(
            "Module.common.config_utils", fromlist=["load_config"]
        )

    def load_config(self, ttl=5):
        return self.config_utils.load_config(ttl=ttl)

    def get_book_paths(self):
        config = self.load_config()
        data_path = config.get("paths", {}).get("book_data_path") or "Module/books/data"
        static_path = (
            config.get("paths", {}).get("book_static_path") or "Module/books/static"
        )
        book_data_path = Path(data_path)
        book_static_path = Path(static_path)
        if not book_data_path.is_absolute():
            book_data_path = BASE_DIR / book_data_path
        if not book_static_path.is_absolute():
            book_static_path = BASE_DIR / book_static_path
        return book_data_path, book_static_path

    def load_books(self):
        global _books_cache, _books_cache_ts
        now = time.time()
        with _books_cache_lock:
            if _books_cache is not None and now - _books_cache_ts < _BOOKS_CACHE_TTL:
                return _books_cache
        books = [
            dict(r)
            for r in self.db.query(
                "SELECT id, title, author, description, detail, cover FROM books ORDER BY id"
            )
        ]
        with _books_cache_lock:
            _books_cache = books
            _books_cache_ts = time.time()
        return books

    def search_books(self, keyword):
        books = self.load_books()
        if not keyword:
            return books
        keyword_lower = keyword.lower()
        return [
            b
            for b in books
            if keyword_lower in b.get("title", "").lower()
            or keyword_lower in b.get("author", "").lower()
            or keyword_lower in b.get("description", "").lower()
        ]

    def get_book(self, book_id):
        books = self.load_books()
        for b in books:
            if b["id"] == book_id:
                return b
        return None

    def get_chapters(self, book_id):
        """获取书籍章节编号列表（已排序）"""
        chapters = []
        book_data_path, _ = self.get_book_paths()
        book_path = book_data_path / str(book_id)
        if book_path.exists():
            for file in book_path.iterdir():
                if file.is_file():
                    match = re.match(r"^(\d+)\.txt$", file.name)
                    if match:
                        chapters.append(int(match.group(1)))
        chapters.sort()
        return chapters

    def get_chapter_content(self, book_id, chapter_num):
        """获取章节内容段落列表；缺失时返回占位提示"""
        book_data_path, _ = self.get_book_paths()
        book_path = book_data_path / str(book_id)
        file_path = book_path / f"{chapter_num}.txt"

        content_text = ""
        if file_path.exists():
            with open(file_path, "r", encoding="utf-8") as f:
                content_text = f.read()

        paragraphs = [line.strip() for line in content_text.split("\n") if line.strip()]
        return paragraphs if paragraphs else ["章节内容未找到"]
