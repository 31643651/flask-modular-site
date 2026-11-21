"""
书籍管理模块（路由层）

职责：仅做请求参数解析、响应渲染与静态文件发送；
业务逻辑（配置路径、书籍加载/搜索/章节、缓存）全部委托 Module.core.books_service.BooksService。
"""

from flask import Blueprint, render_template, send_file, request, abort

from Module.core.books_service import BooksService

# 创建蓝图对象
books_bp = Blueprint("books", __name__, url_prefix="/book", template_folder="templates")

_service = BooksService()


# 功能开关守卫
@books_bp.before_request
def check_books_enabled():
    """检查书籍功能是否启用"""
    from flask import redirect, url_for
    from Module.common.settings_utils import is_feature_enabled

    if not is_feature_enabled("books_enabled"):
        return redirect(url_for("index.index"))


# ============================================================================
# 兼容薄封装（保留原模块级函数名，内部委托服务层）
# ============================================================================


def load_config():
    return _service.load_config()


def get_book_paths():
    return _service.get_book_paths()


def load_books():
    return _service.load_books()


def get_book(book_id):
    return _service.get_book(book_id)


def search_books(search_term):
    return _service.search_books(search_term)


def get_chapters(book_id):
    return _service.get_chapters(book_id)


def get_chapter_content(book_id, chapter_num):
    return _service.get_chapter_content(book_id, chapter_num)


# ============================================================================
# 路由
# ============================================================================
@books_bp.route("")
@books_bp.route("/")
def book_index():
    """
    书籍首页 - 显示所有书籍

    Returns:
        str: 渲染后的搜索页面
    """
    book_data_path, _ = get_book_paths()
    if not book_data_path or not book_data_path.exists():
        return render_template(
            "books/search.html", books=[], search_term="", path_empty=True
        )
    books = load_books()
    return render_template(
        "books/search.html", books=books, search_term="", path_empty=False
    )


@books_bp.route("/search")
def book_search():
    """
    书籍搜索

    Returns:
        str: 渲染后的搜索页面
    """
    book_data_path, _ = get_book_paths()
    if not book_data_path or not book_data_path.exists():
        return render_template(
            "books/search.html", books=[], search_term="", path_empty=True
        )

    search_term = request.args.get("q", "")

    # 分页参数
    try:
        page = int(request.args.get("page", 1))
        per_page = int(request.args.get("per_page", 20))
    except ValueError:
        page, per_page = 1, 20
    page = max(page, 1)
    per_page = min(max(per_page, 1), 100)

    all_books = search_books(search_term)
    total = len(all_books)

    # 分页计算
    total_pages = (total + per_page - 1) // per_page if total > 0 else 1
    start = (page - 1) * per_page
    end = start + per_page
    paginated_books = all_books[start:end]

    return render_template(
        "books/search.html",
        books=paginated_books,
        search_term=search_term,
        path_empty=False,
        page=page,
        total_pages=total_pages,
        total=total,
        per_page=per_page,
    )


@books_bp.route("/<int:book_id>")
def book_detail(book_id):
    """
    书籍详情页

    Args:
        book_id: 书籍 ID

    Returns:
        str: 渲染后的详情页面
    """
    book = get_book(book_id)
    if book is None:
        abort(404)
    chapters = get_chapters(book_id)
    return render_template("books/detail.html", book=book, chapters=chapters)


@books_bp.route("/<int:book_id>/chapter/<int:chapter_num>")
def book_chapter(book_id, chapter_num):
    """
    书籍章节内容页

    Args:
        book_id: 书籍 ID
        chapter_num: 章节编号

    Returns:
        str: 渲染后的章节页面
    """
    book = get_book(book_id)
    if book is None:
        abort(404)
    content = get_chapter_content(book_id, chapter_num)
    return render_template(
        "books/chapter.html", book=book, chapter_num=chapter_num, content=content
    )


@books_bp.route("/static/<path:filename>")
def book_static(filename):
    """
    提供书籍静态资源（图片）

    Args:
        filename: 文件名

    Returns:
        Response: 文件响应或 404 错误
    """
    _, book_static_path = get_book_paths()
    file_path = book_static_path / filename
    # 防目录遍历：解析后必须仍位于静态根内
    try:
        resolved = file_path.resolve()
        root_resolved = book_static_path.resolve()
        resolved.relative_to(root_resolved)
    except ValueError:
        return "Not Found", 404
    # 仅返回文件，目录或不存在一律 404
    if not resolved.is_file():
        return "No image", 404

    content_type = "application/octet-stream"
    if resolved.suffix in (".jpg", ".jpeg"):
        content_type = "image/jpeg"
    elif resolved.suffix == ".png":
        content_type = "image/png"
    elif resolved.suffix == ".gif":
        content_type = "image/gif"
    elif resolved.suffix == ".webp":
        content_type = "image/webp"
    elif resolved.suffix == ".svg":
        content_type = "image/svg+xml"
        # SVG 安全：添加 CSP 头禁止内联脚本，防止 XSS
        response = send_file(resolved, mimetype=content_type)
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; style-src 'unsafe-inline'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.cache_control.max_age = 31536000
        response.cache_control.public = True
        return response
    elif resolved.suffix == ".ico":
        content_type = "image/x-icon"

    response = send_file(resolved, mimetype=content_type)
    response.cache_control.max_age = 31536000
    response.cache_control.public = True
    return response
