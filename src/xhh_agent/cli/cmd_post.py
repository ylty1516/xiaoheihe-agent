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
from xhh_agent.content.plain import markdown_to_plain
from xhh_agent.content.inline_images import replace_inline_images
from xhh_agent.content.stats import MIN_CHARS, check_post, summarize
from xhh_agent.protocol.cos_upload import CosUploader
from xhh_agent.protocol.client import ProtocolClient
from xhh_agent.protocol.errors import LoginExpired, XhhError
from xhh_agent.protocol.session import SessionStore

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_LOGIN_EXPIRED = 3

#: 不指定分区时的落点：PC 游戏。
DEFAULT_TOPIC_ID = "1"


def _split_topic_args(values: list[str] | None) -> tuple[list[str], list[str]]:
    """把 ``--tag`` / ``--topic`` 拆成 (裸 ID, 待解析的名字)。

    ``--tag`` 只接 ID（可一次给多个，用逗号或多次传参），保留旧用法。
    ``--topic`` 接名字或 ID：纯数字当 ID，其余交给话题搜索解析。
    """
    ids: list[str] = []
    names: list[str] = []
    for raw in values or []:
        if raw is None:
            continue
        for piece in str(raw).split(","):
            item = piece.strip()
            if not item:
                continue
            if item.isdigit():
                ids.append(item)
            else:
                names.append(item)
    return ids, names


async def _resolve_topics(
    client: ProtocolClient, ids: list[str], names: list[str]
) -> tuple[list[str], dict[str, str]]:
    """把分区名字解析成 topic_id，返回 (去重后的 ID 列表, 解析结果表)。

    解析不到就 **报错而不是静默跳过**：只挂上 PC 区等于帖子进不了游戏的
    专属分区，作者自己不知道。宁可整次失败。
    """
    resolved: dict[str, str] = {}
    for name in names:
        candidates = await client.search_topics(name)
        if not candidates:
            raise ValueError(
                f"找不到分区「{name}」。先在 App 里确认这个分区叫什么，"
                "或用 --tag 直接指定 ID。"
            )
        # 同名优先，否则取搜索结果第一个（服务端已按相关度排序）
        exact = [c for c in candidates if c["name"] == name]
        chosen = (exact or candidates)[0]
        resolved[name] = chosen["topic_id"]

    ordered: list[str] = []
    for topic_id in ids + list(resolved.values()):
        if topic_id and topic_id not in ordered:
            ordered.append(topic_id)
    return ordered, resolved


def _read_source(path: str) -> str:
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(f"找不到文件：{path}")
    return source.read_text(encoding="utf-8")


async def _run(cfg: Config, args: object, draft: bool) -> int:
    md_path = getattr(args, "md", None)
    html_path = getattr(args, "html", None)
    title = (getattr(args, "title", None) or "").strip()

    # --tag 是裸 ID，--topic 可以是名字。两者都会进分区列表。
    # 默认落 PC 游戏；游戏帖另外用 --topic 挂上游戏专属分区。
    tag_ids, topic_names = _split_topic_args(
        list(getattr(args, "tag", None) or []) + list(getattr(args, "topic", None) or [])
    )
    base_ids = tag_ids or [DEFAULT_TOPIC_ID]

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
            source_text = _read_source(html_path)
            print(f"正文：直接读取文件（{len(source_text)} 字符）")
            markdown_text = ""
        else:
            markdown_text = _read_source(md_path)
            print(f"正文：{md_path}（{len(markdown_text)} 字符 Markdown）")
            source_text = ""

        # 普通动态是纯文本：HTML 标签会被原样显示出来（实测踩过）。
        if markdown_text:
            body_text = markdown_to_heybox_html(markdown_text)
            html = body_text
        else:
            body_text = source_text
            html = source_text
    except FileNotFoundError as exc:
        print(f"参数错误：{exc}", file=sys.stderr)
        return EXIT_USAGE

    if not body_text.strip():
        print("正文转换后为空，已取消。", file=sys.stderr)
        return EXIT_ERROR

    preview = getattr(args, "html_out", None)
    if preview:
        Path(preview).write_text(html, encoding="utf-8")
        print(f"转换结果已保存：{preview}（可先用浏览器打开检查排版）")

    print(f"标题：{title}")
    print(f"正文（HTML，article 模式）：{len(body_text)} 字符")

    # 发帖自检：规则见 voice/content-strategy.md「硬规则」。
    # 这里拿**Markdown 源文**算，不拿转换后的 HTML——HTML 里全是标签，
    # 算出来的“字数”没有意义。
    if markdown_text:
        stats = summarize(markdown_text)
        problems, notes = check_post(markdown_text)
        print(
            f"字数：{stats['chars']}（下限 {MIN_CHARS}）"
            f"  配图：{stats['images']}  表情：{stats['emoji']}"
            f"  喵~：{stats['meow']}  小标题：{stats['headings']}"
        )
        for note in notes:
            print(f"提示：{note}")
        if problems:
            for problem in problems:
                print(f"[X] {problem}", file=sys.stderr)
            if not getattr(args, "allow_short", False):
                print(
                    "\n已中止：不符合发帖硬规则，没有提交。\n"
                    "先改稿（py scripts/check_post.py 稿子.md 可以单独跑），"
                    "确实要发就加 --allow-short。",
                    file=sys.stderr,
                )
                return EXIT_USAGE
            print("⚠ 检测到问题，但带了 --allow-short，照发。", file=sys.stderr)


    try:
        session = SessionStore(session_path(cfg)).load()
    except LoginExpired as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_LOGIN_EXPIRED

    client = ProtocolClient(session, cfg)
    try:
        try:
            topics, resolved = await _resolve_topics(client, base_ids, topic_names)
        except ValueError as exc:
            print(f"分区解析失败：{exc}", file=sys.stderr)
            return EXIT_USAGE
        shown_parts = []
        name_by_id = {topic_id: name for name, topic_id in resolved.items()}
        for topic_id in topics:
            label = name_by_id.get(topic_id)
            shown_parts.append(f"{topic_id}({label})" if label else topic_id)
        print(f"分区：{', '.join(shown_parts)}")
        for name, topic_id in resolved.items():
            print(f"  「{name}」-> {topic_id}")
        if len(topics) < 2:
            print(
                "⚠ 只挂了一个分区。游戏帖建议再加游戏专属分区："
                "--topic \"游戏名\"",
                file=sys.stderr,
            )

        # 结构自检放在图片替换之后：替换前看到 base64 是正常的中转状态。
        # 用 lookbehind 排除 `<strong><pre></strong>` —— 那是正文里行内代码
        # 提到 "<pre>" 这几个字被加粗了，不是残留标签。
        warnings = []
        if re.search(r"(?<!<strong>)<(?:pre|table)[\s>]", html, re.IGNORECASE):
            warnings.append("正文仍含 <pre>/<table> 真标签，小黑盒不支持")
        for warning in warnings:
            print(f"⚠ {warning}", file=sys.stderr)
        if warnings:
            print("已中止，避免发出排版残缺的帖子。", file=sys.stderr)
            return EXIT_ERROR

        result = await client.submit_post(
            title=title,
            content=body_text,
            mode="article",
            topic_ids=topics,
            edit_link_id=str(getattr(args, "edit_link", "") or ""),
            draft=draft,
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
