"""排版层：把 agent 产出的 Markdown 变成小黑盒能正确渲染的 HTML。

职责：
- Markdown → 小黑盒 HTML（白名单窄，代码块和表格渲染成图片）
- 帖子标题/字数校验（超限在本地拦截，不发出去被拒）

约束：
- 不碰网络（转换是纯本地操作；图片以 data URL 内嵌）
- 输入输出都可用快照测试比对
"""

from __future__ import annotations

from .markdown_converter import HeyBoxConverter

__all__ = ["HeyBoxConverter", "markdown_to_heybox_html"]


def markdown_to_heybox_html(markdown_text: str) -> str:
    """Markdown 转小黑盒兼容 HTML 的便捷入口。"""
    if not markdown_text or not markdown_text.strip():
        return ""
    return HeyBoxConverter().convert_markdown(markdown_text)
