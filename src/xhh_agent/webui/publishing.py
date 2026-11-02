"""面板里的发帖通道。

主人 2026-10-30 要面板上有发布按钮。和 CLI 的区别只有一点：
**面板这边把「该拦的」拆成了两级**。

- **挡住（blockers）**：字数/配图不够、选题卡无效、正文完全重复、排期不允许。
  这些是硬规则，按钮直接锁死。
- **提醒（warnings）**：内容近似、排版相近、篇幅偏短（1000–1500）。人要发就发，
  但必须在界面上勾一下「我知道」，不能悄无声息地过去。

规则本身不在这里：字数走 `content.stats`，排期走 `automation.slots`，
内容与排版走 `content.editorial` / `content.style`，CLI 与面板共用。
"""

from __future__ import annotations

import json
from pathlib import Path

import aiohttp

from xhh_agent.automation.slots import DEFAULT_LEDGER, record_post, slot_state
from xhh_agent.automation.publication import acquire
from xhh_agent.config import Config
from xhh_agent.content import markdown_to_heybox_html
from xhh_agent.content.stats import check_post, load_profile, summarize
from xhh_agent.content.writing import GENERAL_TOPIC, load_settings
from xhh_agent.content.topics import pick_topic, topic_key
from xhh_agent.content.preferences import validate_topics
from xhh_agent.content.editorial import load_brief, load_history, record_publication, review
from xhh_agent.content.style import compare_styles
from .editorial import draft_path, read_metadata
from .media import publication_markdown
from xhh_agent.protocol.client import ProtocolClient
from xhh_agent.protocol.errors import LoginExpired, XhhError
from xhh_agent.protocol.session import SessionStore

#: 游戏帖固定要挂的两个分区里的那个公共区
DEFAULT_TOPIC_IDS = ("1",)
DEFAULT_TOPIC_NAME = GENERAL_TOPIC
#: 标题上限按 platform 来，前端也用这个数
MAX_TITLE = 100


def _data_dir(root: Path) -> Path:
    return root / ".data"


def list_drafts(root: Path) -> list[dict]:
    """列出可发的稿子。只认 ``.data/post-*.md``，避免把 README 之类扫进来。"""
    folder = _data_dir(root)
    if not folder.exists():
        return []
    files = sorted(folder.glob("post-*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    out = []
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        stats = summarize(text)
        out.append(
            {
                "name": path.name,
                "chars": stats["chars"],
                "images": stats["images"],
                "suggested_title": _suggest_title(text, path),
                "modified_at": path.stat().st_mtime,
            }
        )
    return out


def _suggest_title(markdown: str, path: Path) -> str:
    """标题建议：正文第一个非标题、非图片的行，截到 30 字。"""
    try:
        metadata_title = read_metadata(path).get("title", "")
        if isinstance(metadata_title, str) and metadata_title.strip():
            return metadata_title.strip()[:MAX_TITLE]
        title = (load_brief(path) or {}).get("title", "")
        if isinstance(title, str) and title.strip():
            return title.strip()[:MAX_TITLE]
    except ValueError:
        pass  # Preflight will explain a malformed card; keep the draft visible.
    for line in markdown.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "!", "|", "```")):
            continue
        return line[:30]
    return path.stem.replace("post-", "")


def _style_check(root: Path, path: Path) -> dict:
    return compare_styles(path.read_text(encoding="utf-8"), load_history(root))


def preflight(root: Path, file_name: str, title: str) -> dict:
    """发帖前的体检结果。**不发任何请求**，可以随便点。"""
    try:
        path = draft_path(root, file_name)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    safe_name = path.name
    if not path.exists():
        return {"ok": False, "error": f"找不到稿子：{safe_name}"}

    markdown = path.read_text(encoding="utf-8")
    stats = summarize(markdown)
    try:
        rules = load_profile(path)
        writing = load_settings(path)
        problems, notes = check_post(markdown, profile=rules.id)
        editorial = review(root, markdown, load_brief(path), brief_advice=rules.id == "article")
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    slot = slot_state(path=root / DEFAULT_LEDGER)
    style = _style_check(root, path)

    blockers = list(problems) + editorial["blockers"]
    if not title.strip():
        blockers.append("还没填标题")
    elif len(title.strip()) > MAX_TITLE:
        blockers.append(f"标题 {len(title.strip())} 字，超过 {MAX_TITLE}")
    if not slot.allowed:
        blockers.append(f"现在不能发：{slot.reason}")

    warnings = list(notes) + editorial["warnings"]
    if not style["ok"]:
        warnings.append(f"排版提醒：{style['detail']}")

    return {
        "ok": not blockers,
        "file": safe_name,
        "title": title,
        "stats": stats,
        "profile": {"id": rules.id, "name": rules.name},
        "writing": {"subject": writing["subject"]["id"], "genre": writing["genre"]["id"]},
        "blockers": blockers,
        "warnings": warnings,
        "style": style,
        "editorial": editorial,
        "slot": {
            "allowed": slot.allowed,
            "reason": slot.reason,
            "today_count": slot.today_count,
            "cap": slot.cap,
            "next_at": slot.next_at,
        },
    }


async def _resolve_topic_ids(
    client: ProtocolClient, names: list[str], *, include_pc=True, strict=False
) -> list[str]:
    ids = list(DEFAULT_TOPIC_IDS) if include_pc else []
    for name in names:
        if name.isdigit():
            if name not in ids:
                ids.append(name)
            continue
        candidates = await client.search_topics(name)
        picked = pick_topic(name, candidates)
        if strict and topic_key(picked["name"]) != topic_key(name):
            raise ValueError(f"没有精确找到分区「{name}」，请重新搜索选择")
        topic_id = str(picked["topic_id"])
        if topic_id not in ids:
            ids.append(topic_id)
    return ids


async def publish(root, cfg, *, file_name, title, topics, accept_warnings, confirm):
    """Serialize WebUI and autopilot submissions across server/CLI processes."""
    if not confirm:
        return {"ok": False, "title": "没有确认，不发", "lines": ["发布要显式确认一次。"]}
    try:
        connection = acquire(root)
    except ValueError:
        return {
            "ok": False,
            "title": "另一个发布正在处理",
            "lines": ["本次尚未提交，请等待当前任务完成"],
        }
    try:
        return await _publish(
            root,
            cfg,
            file_name=file_name,
            title=title,
            topics=topics,
            accept_warnings=accept_warnings,
            confirm=confirm,
        )
    finally:
        connection.close()


async def _publish(
    root: Path,
    cfg: Config,
    *,
    file_name: str,
    title: str,
    topics: list[str],
    accept_warnings: bool,
    confirm: bool,
) -> dict:
    """真发。四道门依次过：确认 → 体检 → 结构提醒 → 额度。"""
    if not confirm:
        return {"ok": False, "title": "没有确认，不发", "lines": ["发布要显式确认一次。"]}

    check = preflight(root, file_name, title)
    if check.get("error"):
        return {"ok": False, "title": "稿子有问题", "lines": [check["error"]]}
    if check["blockers"]:
        return {"ok": False, "title": "被硬规则拦下", "lines": check["blockers"]}
    if check["warnings"] and not accept_warnings:
        return {
            "ok": False,
            "title": "还有提醒没确认",
            "lines": ["勾选「我知道」再来：" + "；".join(check["warnings"])],
        }

    path = _data_dir(root) / check["file"]
    markdown = path.read_text(encoding="utf-8")
    brief = load_brief(path)
    writing = load_settings(path)
    try:
        html = markdown_to_heybox_html(publication_markdown(root, markdown))
    except (OSError, ValueError) as exc:
        return {"ok": False, "title": "配图无法读取", "lines": [str(exc)]}

    # cfg.db_path 可能是相对路径（默认 .data/xhh.db）。面板可能从别处启动，
    # 所以一律按项目根解析，不然会去读一个不存在的 session.json。
    db_path = Path(cfg.db_path)
    if not db_path.is_absolute():
        db_path = root / db_path
    try:
        client = ProtocolClient(SessionStore(db_path.parent / "session.json").load(), cfg)
    except LoginExpired as exc:
        return {"ok": False, "title": "请先登录账号", "lines": [str(exc)]}
    submitted = False
    try:
        stored = read_metadata(path)
        targets = validate_topics(
            topics or stored.get("topics") or [stored.get("topic") or writing["subject"]["topic"]]
        )
        explicit_targets = bool(topics) or "topics" in stored or len(targets) > 1
        topic_ids = await _resolve_topic_ids(
            client,
            targets,
            strict=explicit_targets,
            include_pc=False
            if explicit_targets
            else writing["subject"]["pc"]
            if writing["explicit"]
            else True,
        )
        submitted = True
        result = await client.submit_post(
            title=title.strip(),
            content=html,
            mode="article",
            topic_ids=tuple(topic_ids),
            draft=False,
        )
    except (LoginExpired, XhhError, ValueError) as exc:
        return {"ok": False, "title": "发不出去", "lines": [str(exc)]}
    except (aiohttp.ClientError, OSError, TimeoutError):
        return {
            "ok": False,
            "title": "提交结果未确认" if submitted else "分区查询未完成",
            "lines": [
                "网络请求未完成，请先核对远端结果，勿重复发布"
                if submitted
                else "分区查询未完成，尚未提交正文；稿件已保留"
            ],
        }
    finally:
        await client.close()

    if not result.ok or result.is_draft or not result.link_id:
        return {"ok": False, "title": "接口没回 link_id", "lines": ["按失败处理，去草稿箱核对。"]}

    archive_notes = []
    try:
        record_post(result.link_id, path=root / DEFAULT_LEDGER)
        record_publication(
            root,
            link_id=result.link_id,
            title=title.strip(),
            markdown=markdown,
            brief=brief,
            writing_subject=writing["subject"]["id"] if writing["explicit"] else None,
            writing_genre=writing["genre"]["id"] if writing["genre_explicit"] else None,
        )
    except (OSError, ValueError) as exc:
        # The remote side already succeeded. Never invite a duplicate retry.
        archive_notes.append(f"帖子已公开，勿重发；本地登记失败：{exc}")
    return {
        "ok": True,
        "title": "发出去了",
        "lines": [
            f"link_id：{result.link_id}",
            f"分区：{', '.join(topic_ids)}",
            f"https://www.xiaoheihe.cn/app/bbs/link/{result.link_id}",
        ]
        + archive_notes,
        "link_id": result.link_id,
    }


def drafts_json(root: Path) -> str:
    return json.dumps(list_drafts(root), ensure_ascii=False)
