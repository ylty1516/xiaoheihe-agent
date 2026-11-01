"""Layout diagnostics. Similar formatting is advice, never a content verdict."""

from __future__ import annotations

import re

IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
HEADING_RE = re.compile(r"^#{1,6}\s+(.*)$", re.MULTILINE)


def _body(markdown: str) -> str:
    text = IMAGE_RE.sub("", markdown)
    text = HEADING_RE.sub("", text)
    return text


def _paragraphs(markdown: str) -> list[str]:
    body = _body(markdown)
    blocks = [b.strip() for b in re.split(r"\n\s*\n", body)]
    return [b for b in blocks if b and not re.fullmatch(r"喵[~～!！。\s]*", b)]


def _opening_type(first: str) -> str:
    if first.endswith(("？", "?")):
        return "问句开场"
    if re.search(r"(没人|全都|最|只有|两天|首发|今天|第一)", first[:20]):
        return "事实/判断开场"
    if re.search(r"(我|咱|你)", first[:12]):
        return "第一人称开场"
    return "平铺开场"


def _length_bucket(value: float, cuts: tuple[float, float]) -> str:
    if value < cuts[0]:
        return "短"
    if value < cuts[1]:
        return "中"
    return "长"


def profile(markdown: str) -> dict[str, str]:
    paras = _paragraphs(markdown)
    lengths = [len(re.sub(r"\s", "", p)) for p in paras] or [0]
    avg = sum(lengths) / len(lengths)
    # 段长离散度：标准差/均值，越大越参差
    variance = sum((n - avg) ** 2 for n in lengths) / len(lengths)
    cv = (variance**0.5) / avg if avg else 0
    first = paras[0] if paras else ""
    headings = [h.strip() for h in HEADING_RE.findall(markdown)]
    body_chars = len(re.sub(r"\s", "", _body(markdown)))

    lead_image = bool(IMAGE_RE.search(markdown[:600]))
    last = paras[-1] if paras else ""

    return {
        "小标题个数": _length_bucket(len(headings), (1.5, 3.5)),
        "小标题形态": (
            "无小标题"
            if not headings
            else (
                "编号"
                if all(
                    re.match(r"^(?:\d+[.、]?|[一二三四五六七八九十]+[、.])\s*", h) for h in headings
                )
                else "问句"
                if all(h.endswith(("？", "?")) for h in headings)
                else "短语"
            )
        ),
        "小标题字数": _length_bucket(
            (sum(len(h) for h in headings) / len(headings)) if headings else 0, (7, 11)
        ),
        "段落节奏": _length_bucket(cv, (0.3, 0.6)),
        "开头类型": _opening_type(first),
        "首屏配图": "有" if lead_image else "无",
        "收尾方式": "问句收尾" if last.endswith(("？", "?")) else "陈述收尾",
        "篇幅档位": _length_bucket(body_chars, (1200, 1900)),
    }


def compare_styles(markdown: str, previous: list[dict]) -> dict:
    new = profile(markdown)
    matches = []
    for old in previous[:3]:
        prior = profile(old["markdown"])
        # Heading presence, shape and length are correlated: count them once.
        groups = {
            "小标题组织": ("小标题个数", "小标题形态", "小标题字数"),
            **{k: (k,) for k in ("段落节奏", "开头类型", "首屏配图", "收尾方式", "篇幅档位")},
        }
        same = [label for label, keys in groups.items() if all(new[k] == prior[k] for k in keys)]
        if len(same) >= 5:
            matches.append({"link_id": old.get("link_id", ""), "same": same})
    return {
        "ok": not matches,
        "profile": new,
        "matches": matches,
        "detail": "与最近已发文章形式相近，可检查阅读节奏，无需强行换排版"
        if matches
        else "未发现高度相近的排版；这不代表内容新颖",
    }
