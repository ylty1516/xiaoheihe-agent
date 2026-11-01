"""Subject lenses, article forms and saved draft preferences, independent of length."""

from __future__ import annotations

import json
from pathlib import Path

GENERAL_TOPIC = "盒友杂谈"
SUBJECTS = {
    "auto": {
        "name": "按本次要求",
        "topic": GENERAL_TOPIC,
        "pc": False,
        "guidance": "按给定主题确定题材，不默认写某款游戏，不把所有问题都变成机制分析。",
    },
    "games": {
        "name": "游戏与游戏文化",
        "topic": "PC游戏",
        "pc": True,
        "guidance": "可写不同游戏、资讯、攻略、剧情、设计、独立游戏和游戏文化。区分版本、平台、剧透与推断；没有游玩记录不冒充亲身体验。",
    },
    "hardware": {
        "name": "硬件与外设",
        "topic": GENERAL_TOPIC,
        "pc": False,
        "guidance": "可写电脑硬件、外设、显示设备和使用方法。区分规格、厂商宣称、他人测试与用户实测，比较注明条件，不补跑分或可靠性结论。",
    },
    "software": {
        "name": "软件与开源工具",
        "topic": GENERAL_TOPIC,
        "pc": False,
        "guidance": "可写应用、GitHub项目、开发工具、工作流与教程。保留系统和版本条件、安装前提、许可及功能边界，未运行的步骤不能写成已验证。",
    },
    "ai": {
        "name": "AI工具与应用",
        "topic": GENERAL_TOPIC,
        "pc": False,
        "guidance": "可写AI工具、功能、应用案例、提示词和工作流。注明模型与版本，区分演示、实测和假设，单次样例不等于普遍能力，不承诺未验证的效果。",
    },
}

GENRES = {
    "troubleshooting": (
        "排障攻略",
        ["具体症状与适用版本", "判断分支与操作", "验证结果", "无效时的下一步"],
    ),
    "mechanism": ("机制拆解", ["一个常见误解", "规则及来源", "具体场景与反例", "适用边界"]),
    "debate": ("争议分析", ["双方具体主张", "分别核对证据", "分歧来自哪里", "有条件的判断"]),
    "update": ("更新解读", ["改前与改后", "影响哪些人", "已验证的变化", "尚待验证之处"]),
    "guide": ("选择指南", ["使用场景", "比较维度与证据", "各自取舍", "按场景给建议"]),
    "investigation": ("资料考据", ["需要澄清的疑问", "来源链", "矛盾与缺口", "能确认的结论"]),
    "news": ("资讯与动态", ["可确认的新变化", "时间、出处与背景", "影响和未确认部分"]),
    "tutorial": ("操作教程", ["目标与前提", "操作与结果判据", "常见问题及退出办法"]),
    "review": ("作品或产品评析", ["说明对象与评价依据", "具体观察和解释", "适用人群与边界"]),
    "roundup": ("盘点与合集", ["交代范围和筛选标准", "各条目独有信息", "按使用场景整理"]),
    "narrative": ("叙事与随笔", ["从具体材料或场景进入", "沿事件或观察展开", "自然收束"]),
    "essay": ("观点与短评", ["给出具体判断", "用材料说明理由", "承认边界或回应反例"]),
}


def subject(value="auto") -> dict:
    if not isinstance(value, str) or value not in SUBJECTS:
        raise ValueError("请选择有效的创作领域，或选择按本次要求")
    return {"id": value, **SUBJECTS[value]}


def genre(value="auto") -> dict:
    if value == "auto":
        return {
            "id": value,
            "name": "按内容组织",
            "hint": "按题材和用户要求选择写法，下面的候选路线不是必填模板。",
        }
    if not isinstance(value, str) or value not in GENRES:
        raise ValueError("请选择有效写法，或选择按内容组织")
    return {
        "id": value,
        "name": GENRES[value][0],
        "hint": "可参考的内容要点："
        + "；".join(GENRES[value][1])
        + "。按材料取舍，不要求逐项设章节。",
    }


def load_settings(path: Path, override_subject=None) -> dict:
    meta = path.with_suffix(".meta.json")
    try:
        data = json.loads(meta.read_text(encoding="utf-8")) if meta.exists() else {}
        if not isinstance(data, dict):
            raise ValueError("稿件信息必须是对象")
        selected = subject(
            override_subject if override_subject is not None else data.get("subject", "auto")
        )
        form = genre(data.get("genre", "auto"))
    except (OSError, ValueError) as exc:
        raise ValueError("写作方向读取失败，请检查稿件 .meta.json") from exc
    return {
        "subject": selected,
        "genre": form,
        "explicit": override_subject is not None or "subject" in data,
        "genre_explicit": "genre" in data,
    }


def options() -> dict:
    return {
        "subjects": [subject(k) for k in SUBJECTS],
        "genres": [genre("auto"), *[genre(k) for k in GENRES]],
        "default_topic": GENERAL_TOPIC,
    }
