"""xhh draft / xhh publish：把 Markdown 变成小黑盒帖子。

    xhh draft   --md post.md --title "标题" [--html-out preview.html]
    xhh publish --md post.md --title "标题" --yes

``draft`` 只进草稿箱（不公开），P1 阶段默认走这条。
``publish`` 会真的公开，必须显式 ``--yes``。
"""

from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

from xhh_agent.cli.cmd_login import session_path
from xhh_agent.config import Config
from xhh_agent.content import markdown_to_heybox_html
from xhh_agent.protocol.client import ProtocolClient
from xhh_agent.protocol.errors import LoginExpired, XhhError
from xhh_agent.protocol.session import SessionStore

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_LOGIN_EXPIRED = 3


def _read_source(path: str) -> str:
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(f"找不到文件：{path}")
    return source.read_text(encoding="utf-8")


async def _run(cfg: Config, args: object, draft: bool) -> int:
    md_path = getattr(args, "md", None)
    html_path = getattr(args, "html", None)
    title = (getattr(args, "title", None) or "").strip()
    topic = getattr(args, "tag", None)

    if not title:
        print("参数错误：缺少 --title", file=sys.stderr)
        return EXIT_USAGE
    if not md_path and not html_path:
        print("参数错误：需要 --md 或 --html 其中之一", file=sys.stderr)
        return EXIT_USAGE
    if not draft and not getattr(args, "yes", False):
        print(
            "拒绝执行：正式发布会公开内容，必须显式加 --yes。\n"
            "想先看效果就用 xhh draft（只进草稿箱）。",
            file=sys.stderr,
        )
        return EXIT_USAGE

    try:
        if html_path:
            html = _read_source(html_path)
            print(f"正文：直接读取 HTML（{len(html)} 字符）")
        else:
            markdown_text = _read_source(md_path)
            print(f"正文：{md_path}（{len(markdown_text)} 字符 Markdown）")
            html = markdown_to_heybox_html(markdown_text)
    except FileNotFoundError as exc:
        print(f"参数错误：{exc}", file=sys.stderr)
        return EXIT_USAGE

    if not html.strip():
        print("正文转换后为空，已取消。", file=sys.stderr)
        return EXIT_ERROR

    # 本地结构自检。用正则匹配真正的开标签：正文里提到 `<pre>` 这几个字
    # （行内代码）会变成 <strong><pre></strong>，不该被当成残留标签。
    warnings = []
    if re.search(r"<(?:pre|table)[\s>]", html, re.IGNORECASE):
        warnings.append("正文含 <pre>/<table> 真标签，小黑盒不支持，应转成图片")
    if "data:image/" in html:
        warnings.append(
            "正文含 base64 内嵌图片——实测服务端会拒（'图片链接不合法'），"
            "需要先上传到小黑盒图床拿 URL"
        )

    preview = getattr(args, "html_out", None)
    if preview:
        Path(preview).write_text(html, encoding="utf-8")
        print(f"转换结果已保存：{preview}（可先用浏览器打开检查排版）")

    print(f"标题：{title}")
    print(f"转换后 HTML：{len(html)} 字符" + ("，含图片" if "data:image/" in html else ""))
    for warning in warnings:
        print(f"⚠ {warning}", file=sys.stderr)

    try:
        session = SessionStore(session_path(cfg)).load()
    except LoginExpired as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_LOGIN_EXPIRED

    client = ProtocolClient(session, cfg)
    try:
        result = await client.submit_post(
            title=title,
            html=html,
            draft=draft,
            topic_ids=(str(topic),) if topic else (),
        )
        mode = "草稿" if result.is_draft else "公开发布"
        print(f"\n已{mode}" + (f"，link_id={result.link_id}" if result.link_id else ""))
        if not result.is_draft:
            print("注意：这条帖子已经公开，别人能看到了。")
        return EXIT_OK
    except LoginExpired as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_LOGIN_EXPIRED
    except XhhError as exc:
        print(f"提交失败：{exc}", file=sys.stderr)
        return EXIT_ERROR
    finally:
        await client.close()


def draft_main(args: object, cfg: Config) -> int:
    return asyncio.run(_run(cfg, args, True))


def publish_main(args: object, cfg: Config) -> int:
    return asyncio.run(_run(cfg, args, False))
