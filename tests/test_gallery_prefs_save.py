"""
画廊偏好保存完整性测试（源码锚定）

背景：正方形「发现图片大小」的滑块（discoverSizeRange）曾只写 localStorage、
不调用 updateAndSavePreferences，导致拖动滑块改尺寸后刷新回默认值。
本测试锚定：三个尺寸控件（正方形滑块/数字框、矩形宽/高滑块）都必须保存到服务器。
"""

from pathlib import Path

JS = Path("Module/static/gallery/js/gallery-page.js")


def _handler_body(src, event_line_marker):
    """截取某控件 addEventListener 的处理器函数体（到下一个 }); 为止）"""
    start = src.index(event_line_marker)
    end = src.index("});", start)
    return src[start:end]


class TestDiscoverSizePersistence:
    def test_square_range_slider_saves(self):
        src = JS.read_text(encoding="utf-8")
        body = _handler_body(src, "discoverSizeRange.addEventListener('input'")
        assert "updateAndSavePreferences" in body, (
            "正方形尺寸滑块必须保存到用户偏好，否则刷新后回默认"
        )

    def test_square_number_input_saves(self):
        src = JS.read_text(encoding="utf-8")
        body = _handler_body(src, "discoverSizeInput.addEventListener('input'")
        assert "updateAndSavePreferences" in body

    def test_rectangle_width_slider_saves(self):
        src = JS.read_text(encoding="utf-8")
        body = _handler_body(src, "discoverWidthRange.addEventListener('input'")
        assert "updateAndSavePreferences" in body

    def test_rectangle_height_slider_saves(self):
        src = JS.read_text(encoding="utf-8")
        body = _handler_body(src, "discoverHeightRange.addEventListener('input'")
        assert "updateAndSavePreferences" in body
