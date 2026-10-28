"""排版层：Markdown → 小黑盒兼容 HTML。

小黑盒的 HTML 白名单窄，代码块和表格会直接塌掉，
所以转换器把它们渲染成 Base64 图片内嵌。这些测试钉的就是这个行为。
"""

from xhh_agent.content import markdown_to_heybox_html


def test_paragraph_becomes_p():
    out = markdown_to_heybox_html("这是一段普通文字。")
    assert "<p>" in out
    assert "这是一段普通文字" in out


def test_code_block_becomes_image_not_pre():
    """小黑盒不支持 <pre>，代码块必须变图片，否则发出去是塌的。"""
    out = markdown_to_heybox_html("```python\nprint(1)\n```")
    assert "<pre" not in out.lower()
    assert "data:image/" in out


def test_table_becomes_image_not_table():
    md = "| a | b |\n|---|---|\n| 1 | 2 |"
    out = markdown_to_heybox_html(md)
    assert "<table" not in out.lower()
    assert "|---" not in out


def test_inline_formatting_preserved():
    out = markdown_to_heybox_html("**粗体**")
    assert "粗体" in out
    assert "strong" in out.lower() or "<b>" in out.lower()


def test_heading_text_survives():
    out = markdown_to_heybox_html("## 小标题")
    assert "小标题" in out


def test_external_link_downgraded_to_text():
    """小黑盒不允许外链（防导流），上游故意把它降级成 <strong>文字</strong>（url）。

    直接照抄成 <a href> 会被平台过滤，帖子里那个链接就是死的。
    """
    out = markdown_to_heybox_html("[链接](https://example.com/x)")
    assert "href=" not in out.lower()
    assert "example.com/x" in out


def test_internal_link_keeps_href():
    """站内帖子链接是允许的，必须保留可点的 <a>。"""
    out = markdown_to_heybox_html("[帖](https://www.xiaoheihe.cn/app/bbs/link/123)")
    assert "href=" in out.lower()
    assert "xiaoheihe.cn/app/bbs/link/123" in out


def test_empty_input_returns_empty():
    assert markdown_to_heybox_html("").strip() == ""


def test_plain_text_with_special_chars_is_escaped():
    """正文里的尖括号不能变成真的 HTML 标签。"""
    out = markdown_to_heybox_html("比较 a < b 和 c > d")
    assert "&lt;" in out or "<b" not in out
