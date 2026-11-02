"""Local defaults for new work; a saved draft or task owns its own selection."""

import json

DEFAULT_TOPICS = ("GitHub", "AI")
DEFAULT_SUBJECT = "software"


def validate_topics(values):
    if not isinstance(values, list) or not 1 <= len(values) <= 5:
        raise ValueError("请选择1至5个发布分区")
    result, seen = [], set()
    for value in values:
        if not isinstance(value, str) or not value.strip() or len(value) > 100:
            raise ValueError("分区必须是有效名称或真实ID")
        value = value.strip()
        key = value.casefold()
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result


def load_preferences(root):
    path = root / ".data/authoring-settings.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if not isinstance(data, dict):
        raise ValueError("创作默认设置损坏")
    return {
        "topics": validate_topics(data.get("topics", list(DEFAULT_TOPICS))),
        "subject": DEFAULT_SUBJECT,
        "focus": "github",
    }


def save_preferences(root, data):
    from .editorial import write_json

    if not isinstance(data, dict):
        raise ValueError("创作默认设置必须是对象")
    values = validate_topics(data.get("topics"))
    write_json(root / ".data/authoring-settings.json", {"topics": values})
    return load_preferences(root)
