"""Local draft editing. No account session or network calls are needed."""

from __future__ import annotations

import hashlib
import threading
from pathlib import Path

from xhh_agent.content.editorial import (
    STRUCTURES,
    brief_path,
    empty_brief,
    load_brief,
    load_history,
    plan_options,
    rewrite_prompt,
    validate_brief,
    write_json,
    writing_cards,
)

_EDIT_LOCK = threading.RLock()


def draft_path(root: Path, name: str) -> Path:
    if (
        not name.startswith("post-")
        or not name.endswith(".md")
        or any(c in name for c in "/\\:")
        or Path(name).name != name
    ):
        raise ValueError("稿件名必须是 post-*.md，不能包含路径")
    folder = (root / ".data").resolve()
    path = folder / name
    if path.resolve().parent != folder or brief_path(path).resolve().parent != folder:
        raise ValueError("稿件或选题卡不能指向 .data 以外")
    return path


def revision(path: Path) -> str:
    digest = hashlib.sha256()
    for item in (path, brief_path(path)):
        digest.update(item.read_bytes() if item.exists() else b"<missing>")
    return digest.hexdigest()


def read_draft(root: Path, name: str) -> dict:
    path = draft_path(root, name)
    markdown = path.read_text(encoding="utf-8") if path.exists() else ""
    brief = load_brief(path) or empty_brief()
    suggested = next(
        (
            s.strip()[:30]
            for s in markdown.splitlines()
            if s.strip() and not s.startswith(("#", "!"))
        ),
        "",
    )
    return {
        "ok": True,
        "file": name,
        "markdown": markdown,
        "title": brief.get("title", suggested),
        "brief": brief,
        "revision": revision(path),
        "structures": [{"id": k, "name": v[0]} for k, v in STRUCTURES.items()],
    }


def editor_action(root: Path, body: dict) -> dict:
    # aiohttp dispatches these calls to threads. A stale revision must be
    # checked in the same critical section as the write.
    with _EDIT_LOCK:
        return _editor_action(root, body)


def _editor_action(root: Path, body: dict) -> dict:
    path = draft_path(root, str(body.get("file", "")))
    action = body.get("action")
    brief = body.get("brief", {})
    if action == "save":
        errors = validate_brief(brief, complete=False)
        markdown = body.get("markdown")
        if errors or not isinstance(markdown, str):
            raise ValueError("；".join(errors) or "正文必须是文本")
        if body.get("revision") != revision(path):
            raise ValueError("稿件已被其他窗口修改，请重新读取后合并，尚未覆盖文件")
        path.parent.mkdir(parents=True, exist_ok=True)
        # Save is local only; incomplete cards may be saved but cannot pass preflight.
        write_json(brief_path(path), brief)
        path.write_text(markdown, encoding="utf-8")
        return {"ok": True, "revision": revision(path)}
    if action == "plan":
        plans = plan_options(brief, load_history(root))
        for plan in plans:
            plan["references"] = writing_cards(root, plan["id"])[:2]
        return {"ok": True, "plans": plans}
    if action == "rewrite":
        errors = validate_brief(brief)
        if errors:
            raise ValueError("；".join(errors))
        selected, instruction = body.get("selected", ""), body.get("instruction", "")
        if not isinstance(selected, str) or not isinstance(instruction, str):
            raise ValueError("段落和改写要求必须是文本")
        return {"ok": True, "prompt": rewrite_prompt(brief, selected, instruction)}
    raise ValueError("未知的写作动作")
