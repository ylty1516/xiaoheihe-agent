"""面板里的发帖通道。

主人 2026-10-30 要面板上有发布按钮。和 CLI 的区别只有一点：
**面板这边把「该拦的」拆成了两级**。

- **挡住（blockers）**：字数不到 1000、没有配图、出现 AI 腔词、排期不允许。
  这些是硬规则，按钮直接锁死。
- **提醒（warnings）**：结构撞车、篇幅偏短（1000–1500）。人要发就发，
  但必须在界面上勾一下「我知道」，不能悄无声息地过去。

规则本身不在这里：字数走 `content.stats`，排期走 `automation.slots`，
结构走 `scripts/style_profile.py`。这里只负责把它们串成一次发布。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from xhh_agent.automation.slots import DEFAULT_LEDGER, record_post, slot_state
from xhh_agent.config import Config
from xhh_agent.content import markdown_to_heybox_html
from xhh_agent.content.stats import check_post, summarize
from xhh_agent.protocol.client import ProtocolClient
from xhh_agent.protocol.errors import LoginExpired, XhhError
from xhh_agent.protocol.session import SessionStore

#: 游戏帖固定要挂的两个分区里的那个公共区
DEFAULT_TOPIC_IDS = ("1",)
DEFAULT_TOPIC_NAME = "影之刃零"
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
            }
        )
    return out


def _suggest_title(markdown: str, path: Path) -> str:
    """标题建议：正文第一个非标题、非图片的行，截到 30 字。"""
    for line in markdown.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "!", "|", "```")):
            continue
        return line[:30]
    return path.stem.replace("post-", "")


def _style_check(root: Path, path: Path) -> dict:
    """调 scripts/style_profile.py 判结构撞车。

    走子进程而不是 import：那个脚本在包外，两边各写一份迟早会分叉。
    """
    script = root / "scripts" / "style_profile.py"
    if not script.exists():
        return {"ok": True, "detail": "没有风格检查脚本，跳过"}
    try:
        done = subprocess.run(
            [sys.executable, str(script), "compare", str(path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(root),
            timeout=60,
            check=False,
            # 子进程默认按控制台编码输出，Windows 上是 GBK，解出来就是乱码
            env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": True, "detail": f"风格检查没跑起来：{type(exc).__name__}"}

    text = (done.stdout or "") + (done.stderr or "")
    if done.returncode == 0:
        return {"ok": True, "detail": "结构和最近几篇不一样"}
    collided = [line for line in text.splitlines() if "撞了" in line or "项相同" in line]
    return {"ok": False, "detail": (collided[0].strip() if collided else "结构和旧稿太像")}


def preflight(root: Path, file_name: str, title: str) -> dict:
    """发帖前的体检结果。**不发任何请求**，可以随便点。"""
    safe_name = Path(file_name).name
    path = _data_dir(root) / safe_name
    if not path.exists():
        return {"ok": False, "error": f"找不到稿子：{safe_name}"}

    markdown = path.read_text(encoding="utf-8")
    stats = summarize(markdown)
    problems, notes = check_post(markdown)
    slot = slot_state(path=root / DEFAULT_LEDGER)
    style = _style_check(root, path)

    blockers = list(problems)
    if not title.strip():
        blockers.append("还没填标题")
    elif len(title.strip()) > MAX_TITLE:
        blockers.append(f"标题 {len(title.strip())} 字，超过 {MAX_TITLE}")
    if not slot.allowed:
        blockers.append(f"现在不能发：{slot.reason}")

    warnings = list(notes)
    if not style["ok"]:
        warnings.append(f"结构撞车：{style['detail']}")

    return {
        "ok": not blockers,
        "file": safe_name,
        "title": title,
        "stats": stats,
        "blockers": blockers,
        "warnings": warnings,
        "style": style,
        "slot": {
            "allowed": slot.allowed,
            "reason": slot.reason,
            "today_count": slot.today_count,
            "cap": slot.cap,
            "next_at": slot.next_at,
        },
    }


async def _resolve_topic_ids(client: ProtocolClient, names: list[str]) -> list[str]:
    ids = list(DEFAULT_TOPIC_IDS)
    for name in names:
        candidates = await client.search_topics(name)
        exact = [c for c in candidates if c["name"] == name]
        picked = (exact or candidates or [None])[0]
        if not picked:
            raise ValueError(f"找不到分区「{name}」")
        topic_id = str(picked["topic_id"])
        if topic_id not in ids:
            ids.append(topic_id)
    return ids


async def publish(
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
    html = markdown_to_heybox_html(markdown)

    # cfg.db_path 可能是相对路径（默认 .data/xhh.db）。面板可能从别处启动，
    # 所以一律按项目根解析，不然会去读一个不存在的 session.json。
    db_path = Path(cfg.db_path)
    if not db_path.is_absolute():
        db_path = root / db_path
    client = ProtocolClient(SessionStore(db_path.parent / "session.json").load(), cfg)
    try:
        topic_ids = await _resolve_topic_ids(client, topics or [DEFAULT_TOPIC_NAME])
        result = await client.submit_post(
            title=title.strip(),
            content=html,
            mode="article",
            topic_ids=tuple(topic_ids),
            draft=False,
        )
    except (LoginExpired, XhhError, ValueError) as exc:
        return {"ok": False, "title": "发不出去", "lines": [str(exc)]}
    finally:
        await client.close()

    if not result.link_id:
        return {"ok": False, "title": "接口没回 link_id", "lines": ["按失败处理，去草稿箱核对。"]}

    record_post(result.link_id, path=root / DEFAULT_LEDGER)
    return {
        "ok": True,
        "title": "发出去了",
        "lines": [
            f"link_id：{result.link_id}",
            f"分区：{', '.join(topic_ids)}",
            f"https://www.xiaoheihe.cn/app/bbs/link/{result.link_id}",
        ],
        "link_id": result.link_id,
    }


def drafts_json(root: Path) -> str:
    return json.dumps(list_drafts(root), ensure_ascii=False)
