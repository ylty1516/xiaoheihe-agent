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

import aiohttp

from xhh_agent.cli.cmd_login import session_path
from xhh_agent.automation.publication import acquire
from xhh_agent.automation.slots import DEFAULT_LEDGER, record_post
from xhh_agent.config import Config
from xhh_agent.content import markdown_to_heybox_html
from xhh_agent.content.plain import markdown_to_plain
from xhh_agent.content.inline_images import replace_inline_images
from xhh_agent.content.stats import check_post, load_profile, summarize
from xhh_agent.content.editorial import load_brief, record_publication, review
from xhh_agent.content.topics import pick_topic
from xhh_agent.content.writing import load_settings
from xhh_agent.protocol.cos_upload import CosUploader
from xhh_agent.protocol.client import ProtocolClient
from xhh_agent.protocol.errors import LoginExpired, XhhError
from xhh_agent.protocol.session import SessionStore

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_LOGIN_EXPIRED = 3


def _editorial_root(source: Path) -> Path:
    """Use the project containing the source, falling back to the working directory."""
    for folder in source.resolve().parents:
        if (folder / "pyproject.toml").exists():
            return folder
    return Path.cwd()


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
                f"找不到分区「{name}」。先在 App 里确认这个分区叫什么，或用 --tag 直接指定 ID。"
            )
        chosen = pick_topic(name, candidates)
        resolved[name] = str(chosen["topic_id"])

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
        writing = load_settings(Path(md_path or html_path), getattr(args, "subject", None))
        if writing["explicit"]:
            base_ids = tag_ids or ([DEFAULT_TOPIC_ID] if writing["subject"]["pc"] else [])
            if not base_ids and not topic_names:
                topic_names = [writing["subject"]["topic"]]
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
    except (FileNotFoundError, ValueError) as exc:
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
    brief = None
    editorial_root = _editorial_root(Path(md_path)) if md_path else Path.cwd()
    if markdown_text:
        try:
            rules = load_profile(Path(md_path), getattr(args, "profile", None))
        except ValueError as exc:
            print(f"内容规格错误：{exc}", file=sys.stderr)
            return EXIT_USAGE
        stats = summarize(markdown_text)
        problems, notes = check_post(markdown_text, profile=rules.id)
        print(
            f"内容规格：{rules.name}  字数：{stats['chars']}（下限 {rules.min_chars}）"
            f"  配图：{stats['images']}  表情：{stats['emoji']}"
            f"  喵~：{stats['meow']}  小标题：{stats['headings']}"
        )
        for note in notes:
            print(f"提示：{note}")
        if problems:
            for problem in problems:
                print(f"{'草稿提示：' if draft else '[X] '}{problem}", file=sys.stderr)
            if not draft and not getattr(args, "allow_short", False):
                print(
                    "\n已中止：不符合发帖硬规则，没有提交。\n"
                    "先改稿（py scripts/check_post.py 稿子.md 可以单独跑），"
                    "短帖或无图稿可选 --profile short / flexible；旧用法 --allow-short 仍可用。",
                    file=sys.stderr,
                )
                return EXIT_USAGE
            print(
                "草稿可以未完成，保存后继续编辑。"
                if draft
                else "⚠ 已按 --allow-short 放行内容规格提醒。",
                file=sys.stderr,
            )

        try:
            brief = load_brief(Path(md_path))
            editorial = review(
                editorial_root,
                markdown_text,
                brief,
                exclude_link_id=str(getattr(args, "edit_link", "") or ""),
                brief_advice=rules.id == "article",
            )
        except ValueError as exc:
            print(f"写作检查失败：{exc}", file=sys.stderr)
            return EXIT_USAGE
        for note in editorial["warnings"]:
            print(f"写作提醒：{note}")
        if editorial["blockers"]:
            for problem in editorial["blockers"]:
                print(f"{'草稿提示：' if draft else '[X] '}{problem}", file=sys.stderr)
            if not draft:
                return EXIT_USAGE

    try:
        session = SessionStore(session_path(cfg)).load()
    except LoginExpired as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_LOGIN_EXPIRED

    client = ProtocolClient(session, cfg)
    submitted = False
    publication_lease = None
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
        if len(topics) < 2 and (not writing["explicit"] or writing["subject"]["pc"]):
            print(
                '⚠ 只挂了一个分区。游戏帖建议再加游戏专属分区：--topic "游戏名"',
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

        if not draft:
            try:
                publication_lease = acquire(editorial_root)
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return EXIT_ERROR
        submitted = True
        result = await client.submit_post(
            title=title,
            content=body_text,
            mode="article",
            topic_ids=topics,
            edit_link_id=str(getattr(args, "edit_link", "") or ""),
            draft=draft,
        )
        if not result.ok:
            print(f"提交失败：{result.message or '服务端未确认成功'}", file=sys.stderr)
            return EXIT_ERROR
        mode = "草稿" if result.is_draft else "公开发布"
        print(f"\n已{mode}" + (f"，link_id={result.link_id}" if result.link_id else ""))
        if not result.is_draft:
            print("注意：这条帖子已经公开，别人能看到了。")
            if result.link_id:
                try:
                    record_post(result.link_id, path=editorial_root / DEFAULT_LEDGER)
                except (OSError, ValueError):
                    print("帖子已公开，勿重发；本地排期登记失败，请核对后补录。", file=sys.stderr)
            if markdown_text and result.ok and result.link_id:
                try:
                    record_publication(
                        editorial_root,
                        link_id=result.link_id,
                        title=title,
                        markdown=markdown_text,
                        brief=brief,
                        writing_subject=writing["subject"]["id"] if writing["explicit"] else None,
                        writing_genre=writing["genre"]["id"] if writing["genre_explicit"] else None,
                    )
                except (OSError, ValueError) as exc:
                    print(f"帖子已公开，勿重发；内容快照登记失败：{exc}", file=sys.stderr)
        return EXIT_OK
    except LoginExpired as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_LOGIN_EXPIRED
    except XhhError as exc:
        print(f"提交失败：{exc}", file=sys.stderr)
        return EXIT_ERROR
    except (aiohttp.ClientError, OSError, TimeoutError):
        print(
            "提交结果未确认，请核对远端，勿重复发布。"
            if submitted
            else "分区查询未完成，尚未提交正文；稿件已保留。",
            file=sys.stderr,
        )
        return EXIT_ERROR
    finally:
        if publication_lease:
            publication_lease.close()
        await client.close()


def draft_main(args: object, cfg: Config) -> int:
    return asyncio.run(_run(cfg, args, True))


def publish_main(args: object, cfg: Config) -> int:
    return asyncio.run(_run(cfg, args, False))
