"""Local draft editing. No account session or network calls are needed."""

from __future__ import annotations

import hashlib
import re
import threading
import json
import time
import uuid
from pathlib import Path

from xhh_agent.content.preferences import load_preferences, validate_topics
from xhh_agent.content.stats import get_profile, load_profile
from xhh_agent.content.writing import GENERAL_TOPIC, subject, genre
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
    for item in (path, brief_path(path), path.with_suffix(".meta.json")):
        digest.update(item.read_bytes() if item.exists() else b"<missing>")
    return digest.hexdigest()


def read_draft(root: Path, name: str) -> dict:
    path = draft_path(root, name)
    markdown = path.read_text(encoding="utf-8") if path.exists() else ""
    brief = load_brief(path) or empty_brief()
    meta = read_metadata(path)
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
        "title": meta.get("title", brief.get("title", suggested)),
        "brief": brief,
        "has_brief": brief_path(path).exists(),
        "metadata": meta,
        "revision": revision(path),
        "structures": [{"id": k, "name": v[0]} for k, v in STRUCTURES.items()],
    }


def editor_action(root: Path, body: dict) -> dict:
    # aiohttp dispatches these calls to threads. A stale revision must be
    # checked in the same critical section as the write.
    with _EDIT_LOCK:
        return _editor_action(root, body)


def _editor_action(root: Path, body: dict) -> dict:
    if body.get("action") in {"new", "duplicate", "archive", "restore"}:
        return manage_draft(root, body)
    path = draft_path(root, str(body.get("file", "")))
    action = body.get("action")
    brief = body.get("brief")
    if action == "save":
        errors = validate_brief(brief, complete=False) if brief is not None else []
        markdown = body.get("markdown")
        if errors or not isinstance(markdown, str):
            raise ValueError("；".join(errors) or "正文必须是文本")
        meta = body.get("metadata")
        if meta is not None and (
            not isinstance(meta, dict) or not isinstance(meta.get("title", ""), str)
        ):
            raise ValueError("稿件信息格式错误")
        if meta is not None:
            previous_meta = read_metadata(path)
            persona_ref = meta.get("persona", previous_meta.get("persona"))
            if persona_ref is not None and (
                not isinstance(persona_ref, dict)
                or not isinstance(persona_ref.get("id"), str)
                or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", persona_ref["id"])
                or type(persona_ref.get("revision")) is not int
                or persona_ref["revision"] < 0
                or not isinstance(persona_ref.get("digest"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", persona_ref["digest"])
            ):
                raise ValueError("人设版本记录无效")
            if persona_ref:
                persona_ref = {
                    k: persona_ref[k]
                    for k in ("id", "revision", "digest", "policy_version")
                    if k in persona_ref
                }
            selected_topics = (
                validate_topics(meta["topics"])
                if "topics" in meta
                else [str(meta["topic"]).strip()]
                if "topic" in meta
                else validate_topics(previous_meta["topics"])
                if "topics" in previous_meta
                else None
            )
            if selected_topics is not None:
                selected_topics = validate_topics(selected_topics)
            selected_subject = subject(meta.get("subject", previous_meta.get("subject", "auto")))
            selected_genre = genre(meta.get("genre", previous_meta.get("genre", "auto")))
            saved_profile = (
                get_profile(meta["profile"]) if "profile" in meta else load_profile(path)
            ).id
        if body.get("revision") != revision(path):
            raise ValueError("稿件已被其他窗口修改，请重新读取后合并，尚未覆盖文件")
        path.parent.mkdir(parents=True, exist_ok=True)
        # Save is local only; incomplete cards may be saved but cannot pass preflight.
        if brief is not None:
            write_json(brief_path(path), brief)
        if meta is not None:
            write_json(
                path.with_suffix(".meta.json"),
                {
                    "title": meta.get("title", "")[:100],
                    "topic": selected_topics[0]
                    if selected_topics
                    else str(meta.get("topic", previous_meta.get("topic", GENERAL_TOPIC)))[:100],
                    **({"topics": selected_topics} if selected_topics is not None else {}),
                    "notes": str(meta.get("notes", ""))[:40_000],
                    "profile": saved_profile,
                    **({"persona": persona_ref} if persona_ref else {}),
                    **(
                        {"subject": selected_subject["id"]}
                        if "subject" in meta or "subject" in previous_meta
                        else {}
                    ),
                    **(
                        {"genre": selected_genre["id"]}
                        if "genre" in meta or "genre" in previous_meta
                        else {}
                    ),
                },
            )
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


def read_metadata(path: Path) -> dict:
    file = path.with_suffix(".meta.json")
    if not file.exists():
        return {}
    data = json.loads(file.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("稿件信息损坏")
    return data


def archive_folder(root: Path) -> Path:
    base = (root / ".data").resolve()
    path = base / "draft-archive"
    if path.resolve().parent != base:
        raise ValueError("回收站路径无效")
    return path


def archived_drafts(root: Path) -> list[dict]:
    result = []
    for file in archive_folder(root).glob("*/manifest.json"):
        data = json.loads(file.read_text(encoding="utf-8"))
        result.append({**data, "archive_id": file.parent.name})
    return sorted(result, key=lambda x: x["archived_at"], reverse=True)


def manage_draft(root: Path, body: dict) -> dict:
    action = body["action"]
    if action == "restore":
        archive_id = str(body.get("archive_id", ""))
        if len(archive_id) != 32 or any(c not in "0123456789abcdef" for c in archive_id):
            raise ValueError("回收记录无效")
        folder = archive_folder(root) / archive_id
        if folder.resolve().parent != archive_folder(root).resolve():
            raise ValueError("回收记录路径无效")
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        target = draft_path(root, manifest["file"])
        if target.exists():
            target = draft_path(root, f"post-restored-{uuid.uuid4().hex[:12]}.md")
        for suffix in (".md", ".brief.json", ".meta.json"):
            source = folder / ("draft" + suffix)
            if source.exists():
                source.replace(target.with_suffix(suffix))
        (folder / "manifest.json").unlink()
        folder.rmdir()
        return read_draft(root, target.name)
    if action == "new":
        target = draft_path(root, f"post-{time.strftime('%Y%m%d')}-{uuid.uuid4().hex[:12]}.md")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("", encoding="utf-8")
        write_json(
            target.with_suffix(".meta.json"),
            {
                "title": "",
                "topic": load_preferences(root)["topics"][0],
                "topics": load_preferences(root)["topics"],
                "subject": "software",
                "genre": "auto",
            },
        )
        return read_draft(root, target.name)
    source = draft_path(root, str(body.get("file", "")))
    if not source.exists():
        raise ValueError("稿件不存在")
    if body.get("revision") != revision(source):
        raise ValueError("稿件已变化，请重新读取后操作")
    if action == "duplicate":
        target = draft_path(root, f"post-copy-{uuid.uuid4().hex[:12]}.md")
        for suffix in (".md", ".brief.json", ".meta.json"):
            old = source.with_suffix(suffix)
            if old.exists():
                target.with_suffix(suffix).write_bytes(old.read_bytes())
        data = read_draft(root, target.name)
        write_json(
            target.with_suffix(".meta.json"),
            {**data["metadata"], "title": (data["title"] or "未命名") + "（副本）"},
        )
        return read_draft(root, target.name)
    folder = archive_folder(root) / uuid.uuid4().hex
    folder.mkdir(parents=True)
    write_json(
        folder / "manifest.json",
        {
            "file": source.name,
            "title": read_draft(root, source.name)["title"] or "未命名稿件",
            "archived_at": time.time(),
        },
    )
    for suffix in (".md", ".brief.json", ".meta.json"):
        old = source.with_suffix(suffix)
        if old.exists():
            old.replace(folder / ("draft" + suffix))
    return {"ok": True}
