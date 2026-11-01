"""Evidence-first planning and conservative, offline repetition checks.

Similarity is a textual signal, not a semantic or factual verdict. Only successful
publications enter history; draft mtimes never determine the comparison set.
"""

from __future__ import annotations

import json
import math
import os
import re
import tempfile
import time
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import urlparse

from .diversity import ROUTES, audit, reused_images
from .writing import GENRES as STRUCTURES
from .writing import subject, genre

HISTORY = Path(".data/editorial-history.json")
BRIEF_FIELDS = ("reader", "question", "conclusion", "new_information")


def brief_path(path: Path) -> Path:
    return path.with_suffix(".brief.json")


def empty_brief() -> dict:
    return {**dict.fromkeys(BRIEF_FIELDS, ""), "structure": "mechanism", "exclude": [], "facts": []}


def validate_brief(brief: object, *, complete: bool = True) -> list[str]:
    if not isinstance(brief, dict):
        return ["选题卡必须是 JSON 对象"]
    errors = []
    for key in BRIEF_FIELDS:
        value = brief.get(key, "")
        if not isinstance(value, str) or (complete and not value.strip()):
            errors.append(f"选题卡缺少文本字段：{key}")
    if brief.get("structure") not in STRUCTURES:
        errors.append("请选择有效的文章类型")
    route = brief.get("route")
    if route:
        if not isinstance(route, str) or route not in ROUTES:
            errors.append("请选择有效的论证路线 route，或留空按材料决定")
        elif brief.get("structure") not in ROUTES[route]["types"]:
            errors.append("论证路线 route 与文章类型不匹配，请按实际材料选择")
    exclude = brief.get("exclude", [])
    if not isinstance(exclude, list) or any(not isinstance(x, str) for x in exclude):
        errors.append("不再展开的内容必须是文本列表")
    facts = brief.get("facts", [])
    if not isinstance(facts, list):
        return errors + ["证据必须是列表"]
    if complete and not facts:
        errors.append("至少填写一条具体事实和来源；没有素材先不写正文")
    for fact in facts:
        if not isinstance(fact, dict):
            errors.append("每条证据必须包含 claim 和 source")
            continue
        claim, source = fact.get("claim"), fact.get("source")
        if not isinstance(claim, str) or not claim.strip():
            errors.append("证据缺少具体事实 claim")
        if not isinstance(source, str) or not re.match(r"^https?://[^\s]+$", source):
            errors.append("证据来源 source 必须是 http(s) 链接")
        elif not urlparse(source).netloc:
            errors.append("证据来源缺少域名")
    return errors


def load_brief(path: Path) -> dict | None:
    sidecar = brief_path(path)
    if not sidecar.exists():
        return None
    try:
        value = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"选题卡读取失败：{sidecar.name}") from exc
    errors = validate_brief(value, complete=False)
    if errors:
        raise ValueError("；".join(errors))
    return value


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def load_history(root: Path) -> list[dict]:
    path = root / HISTORY
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list) or any(
            not isinstance(x, dict)
            or not isinstance(x.get("markdown"), str)
            or not isinstance(x.get("title"), str)
            or not isinstance(x.get("link_id"), str)
            or not isinstance(x.get("brief", {}), dict)
            or not isinstance(x.get("published_at"), (float, int))
            or isinstance(x.get("published_at"), bool)
            or not math.isfinite(x["published_at"])
            or x["published_at"] <= 0
            for x in data
        ):
            raise ValueError("历史格式错误")
        if any(x.get("brief") and validate_brief(x["brief"], complete=False) for x in data):
            raise ValueError("历史选题卡格式错误")
    except (OSError, ValueError) as exc:
        raise ValueError("已发布内容历史读取失败，请修复 .data/editorial-history.json") from exc
    return sorted(data, key=lambda x: x["published_at"], reverse=True)


def record_publication(
    root: Path,
    *,
    link_id: str,
    title: str,
    markdown: str,
    brief: dict | None = None,
    published_at: float | None = None,
    writing_subject: str | None = None,
    writing_genre: str | None = None,
) -> None:
    if not link_id:
        raise ValueError("没有 link_id 不能登记已发布内容")
    history = load_history(root)
    previous = next((x for x in history if x["link_id"] == str(link_id)), {})
    scope = subject(
        writing_subject if writing_subject is not None else previous.get("subject", "auto")
    )
    form = genre(writing_genre if writing_genre is not None else previous.get("genre", "auto"))
    stamp = published_at if published_at is not None else previous.get("published_at", time.time())
    if (
        isinstance(stamp, bool)
        or not isinstance(stamp, (int, float))
        or not math.isfinite(stamp)
        or stamp <= 0
    ):
        raise ValueError("发布时间必须是有效的正数 Unix 时间戳")
    entries = [x for x in history if x.get("link_id") != str(link_id)]
    entries.insert(
        0,
        {
            "link_id": str(link_id),
            "title": title,
            "markdown": markdown,
            "brief": brief or {},
            "published_at": stamp,
            "subject": scope["id"],
            "genre": form["id"],
        },
    )
    write_json(root / HISTORY, entries)


def normalize(text: str) -> str:
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\[cube_[^\]]+\]|喵[~～]?", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    return re.sub(r"[^\w\u4e00-\u9fff]", "", text).lower()


def paragraphs(markdown: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", markdown) if len(normalize(p)) >= 24]


def _similar(a: str, b: str) -> float:
    a, b = normalize(a), normalize(b)
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b, autojunk=False).ratio()


def _shingles(text: str) -> set[str]:
    return {text[i : i + 5] for i in range(max(0, len(text) - 4))}


def review(
    root: Path,
    markdown: str,
    brief: dict | None,
    *,
    require_brief=False,
    exclude_link_id: str = "",
    brief_advice: bool = True,
) -> dict:
    blockers, warnings, matches = [], [], []
    if brief is None:
        if require_brief or brief_advice:
            (blockers if require_brief else warnings).append(
                "缺少选题卡，无法比较核心问题、结论与证据"
            )
    else:
        errors = validate_brief(brief)
        if errors:
            return {
                "blockers": errors,
                "warnings": [],
                "matches": [],
                "history_count": 0,
                "method": "先补全选题卡，再检查内容重复",
            }
    history = [x for x in load_history(root) if x["link_id"] != exclude_link_id][:20]
    if not history:
        warnings.append("尚无已发布内容快照，不能据此判定内容不重复；旧文可用 import 补录")
    new_text = normalize(markdown)
    new_set = _shingles(new_text)
    new_paras = paragraphs(markdown)
    for old in history:
        old_text = normalize(old["markdown"])
        old_set = _shingles(old_text)
        similarity = len(new_set & old_set) / max(1, len(new_set | old_set))
        old_paras = paragraphs(old["markdown"])
        repeated = []
        for i, para in enumerate(new_paras):
            best = max(old_paras, key=lambda p: _similar(para, p), default="")
            if best and _similar(para, best) >= 0.88:
                repeated.append({"paragraph": i + 1, "text": para, "previous": best})
        prior = old.get("brief", {})
        same_claim = bool(
            brief
            and all(
                _similar(brief.get(key, ""), prior.get(key, "")) >= 0.82
                for key in ("question", "conclusion")
            )
        )
        reused = [
            f["claim"]
            for f in (brief or {}).get("facts", [])
            if any(
                _similar(f["claim"], p.get("claim", "")) >= 0.85
                for p in prior.get("facts", [])
                if isinstance(p, dict)
            )
        ]
        if len(new_text) >= 200 and new_text == old_text:
            blockers.append(f"正文与已发布《{old['title']}》相同，请补充实质新信息")
        if repeated or same_claim or reused or similarity >= 0.45:
            matches.append(
                {
                    "link_id": old["link_id"],
                    "title": old["title"],
                    "similarity": round(similarity, 3),
                    "same_claim": same_claim,
                    "reused_facts": reused,
                    "repeated_paragraphs": repeated,
                }
            )
            warnings.append(
                f"与《{old['title']}》存在重复线索：{len(repeated)} 段近似、"
                f"{len(reused)} 条事实复用"
                + ("，核心问题和结论近似" if same_claim else "")
                + "；保留新增信息，核对是否需要删减旧内容"
            )
    diversity = audit(history, markdown)
    warnings.extend(diversity["warnings"])
    images = reused_images(markdown, history)
    for image in images:
        warnings.append(
            f"配图复用：与《{image['title']}》使用了 {image['count']} 个相同图片资源；"
            "核对是否确实服务本篇证据，不根据不同缩略图地址判断图片不同"
        )
    return {
        "blockers": blockers,
        "warnings": warnings,
        "matches": matches,
        "history_count": len(history),
        "diversity": diversity,
        "reused_images": images,
        "method": "文本近似与选题卡线索，不能证明语义新颖或事实正确",
    }


def plan_options(brief: dict, history: list[dict]) -> list[dict]:
    errors = validate_brief(brief)
    if errors:
        raise ValueError("；".join(errors))
    recent = [x.get("brief", {}).get("structure") for x in history[:3]]
    related = {
        "troubleshooting": ("mechanism", "guide", "investigation"),
        "mechanism": ("investigation", "troubleshooting", "debate"),
        "debate": ("investigation", "guide", "mechanism"),
        "update": ("investigation", "guide", "mechanism"),
        "guide": ("mechanism", "investigation", "troubleshooting"),
        "investigation": ("mechanism", "debate", "update"),
        "news": ("update", "investigation", "roundup"),
        "tutorial": ("troubleshooting", "guide", "mechanism"),
        "review": ("guide", "essay", "investigation"),
        "roundup": ("guide", "news", "review"),
        "narrative": ("review", "essay", "investigation"),
        "essay": ("debate", "review", "investigation"),
    }[brief["structure"]]
    keys = [brief["structure"], *sorted(related, key=recent.count)[:2]]
    used = [x.get("brief", {}).get("route") for x in history[:5]]
    selected_routes, plans = set(), []
    for key in keys:
        candidates = [r for r, value in ROUTES.items() if key in value["types"]]
        route_id = min(
            candidates,
            key=lambda r: (
                r in selected_routes,
                r != brief.get("route") if key == brief["structure"] else False,
                used.count(r),
            ),
        )
        selected_routes.add(route_id)
        route = ROUTES[route_id]
        plans.append(
            {
                "id": key,
                "name": STRUCTURES[key][0],
                "route": route_id,
                "route_name": route["name"],
                "reader_gain": route["gain"],
                "entry": route["entry"],
                "sections": route["sections"],
                "ending": route["ending"],
                "evidence_needed": route["needs"],
                "image_roles": route["images"],
                "question": brief["question"],
                "new_information": brief["new_information"],
                "evidence": brief["facts"],
                "recent_habits": audit(history)["patterns"],
                "note": "这些是候选推理路径，不是固定章节。先核对素材是否够用；不足就补证据或收窄结论，不为轮换而虚构",
            }
        )
    return plans


def rewrite_prompt(brief: dict, selected: str, instruction: str) -> str:
    if not selected.strip() or not instruction.strip():
        raise ValueError("先选中要改的段落，并填写改写要求")
    return (
        "只改下列选中段落，其余正文保持原样。保留事实、数值、来源与适用边界，"
        "不得新增游玩经历或未经证实的结论。只输出替换段落。\n"
        f"选题卡与证据：\n{json.dumps(brief, ensure_ascii=False)}\n"
        f"改写要求：{instruction}\n选中段落：\n{selected}"
    )


def save_writing_card(root: Path, card: object) -> Path:
    """Accept a completed analysis, never label automatically fetched text as learned."""
    if not isinstance(card, dict):
        raise ValueError("写法卡必须是对象")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", str(card.get("link_id", ""))):
        raise ValueError("写法卡缺少有效 link_id")
    if card.get("article_type") not in STRUCTURES:
        raise ValueError("写法卡 article_type 必须是支持的文章类型")
    for key in ("reader_question", "applicable_when", "source_url"):
        if not isinstance(card.get(key), str) or not card[key].strip():
            raise ValueError(f"写法卡缺少 {key}")
    if not re.match(r"^https?://[^\s]+$", card["source_url"]):
        raise ValueError("写法卡来源必须是 http(s) 链接")
    for key in ("argument_order", "evidence_usage", "avoid"):
        value = card.get(key)
        if not isinstance(value, list) or any(not isinstance(x, str) for x in value):
            raise ValueError(f"写法卡 {key} 必须是文本列表")
        if key != "avoid" and not value:
            raise ValueError(f"写法卡 {key} 不能为空")
    path = root / "notes/study/cards" / f"{card['link_id']}.json"
    write_json(path, {**card, "status": "ready"})
    return path


def writing_cards(root: Path, query: str = "") -> list[dict]:
    cards = []
    for path in sorted((root / "notes/study/cards").glob("*.json")):
        card = json.loads(path.read_text(encoding="utf-8"))
        if (
            card.get("status") == "ready"
            and query.lower() in json.dumps(card, ensure_ascii=False).lower()
        ):
            cards.append(card)
    return cards
