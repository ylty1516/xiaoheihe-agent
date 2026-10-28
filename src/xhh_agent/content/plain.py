"""Markdown → 纯文本。

为什么需要：小黑盒**普通动态不支持任何 HTML**。`type="text"` 的 block
会把 `<h2>` 这类标签原样显示出来（实测：帖子里出现了 HTML 源码）。

只有文章（`post_type=2`）才解析富文本，但文章需要封面图和创作计划。
所以短动态走纯文本，长文再用文章模式。
"""

from __future__ import annotations

import re

_RE_HEADING = re.compile(r"^#{1,6}\s*", re.MULTILINE)
_RE_BOLD_ITALIC = re.compile(r"\*{1,3}([^*\n]+)\*{1,3}")
_RE_UNDERSCORE = re.compile(r"_{1,2}([^_\n]+)_{1,2}")
_RE_INLINE_CODE = re.compile(r"`([^`\n]+)`")
_RE_STRIKE = re.compile(r"~~([^~\n]+)~~")
_RE_TABLE_SEP = re.compile(r"^\s*\|?[\s:|-]+\|[\s:|-]*$", re.MULTILINE)
_RE_TABLE_PIPE = re.compile(r"^\s*\|(.+)\|\s*$", re.MULTILINE)
_RE_IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
_RE_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_RE_CODE_FENCE = re.compile(r"```[a-zA-Z0-9]*\n?")
_RE_BLANK_LINES = re.compile(r"\n{3,}")


def markdown_to_plain(markdown_text: str) -> str:
    """把 Markdown 压成纯文本，保留段落结构。"""
    text = markdown_text or ""
    if not text.strip():
        return ""

    # 代码块标记去掉，内容保留（纯文本里没法渲染，至少不漏内容）
    text = _RE_CODE_FENCE.sub("", text)

    # 表格转成「a / b」这种隔开的形式，去掉分隔行
    text = _RE_TABLE_SEP.sub("", text)

    def _table_row(match: re.Match[str]) -> str:
        cells = [c.strip() for c in match.group(1).split("|")]
        return "  ".join(c for c in cells if c)

    text = _RE_TABLE_PIPE.sub(_table_row, text)

    # 图片：动态里带不了图，留成文字说明
    text = _RE_IMAGE.sub(lambda m: f"（图片：{m.group(1) or m.group(2)}）", text)
    # 链接保留「文字 url」，纯文本里没有超链接
    text = _RE_LINK.sub(lambda m: f"{m.group(1)}（{m.group(2)}）", text)

    text = _RE_HEADING.sub("", text)
    text = _RE_BOLD_ITALIC.sub(r"\1", text)
    text = _RE_UNDERSCORE.sub(r"\1", text)
    text = _RE_INLINE_CODE.sub(r"\1", text)
    text = _RE_STRIKE.sub(r"\1", text)

    text = _RE_BLANK_LINES.sub("\n\n", text)
    return text.strip()
