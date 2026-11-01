"""Resolve names without silently substituting an unrelated fuzzy first hit."""

import re
import unicodedata


def topic_key(value: str) -> str:
    return re.sub(r"[\W_]", "", unicodedata.normalize("NFKC", value)).casefold()


def pick_topic(name: str, candidates: list[dict]) -> dict:
    if not isinstance(name, str) or not name.strip():
        raise ValueError("分区名称不能为空")
    valid = [
        x
        for x in candidates
        if isinstance(x, dict) and x.get("topic_id") and isinstance(x.get("name"), str)
    ]
    if not valid:
        raise ValueError(f"找不到分区「{name}」，请查找实际分区名或使用真实 ID")
    exact = [x for x in valid if topic_key(x["name"]) == topic_key(name)]
    if exact:
        return exact[0]
    if len(valid) == 1:
        return valid[0]
    names = "、".join(x["name"] for x in valid[:5])
    raise ValueError(f"分区「{name}」有多个可能结果：{names}；请指定实际分区名或 ID")
