"""Observable writing habits, separate from textual duplication or fact checking.

These signals describe a small recent sample. They neither grade an author's
voice nor certify semantic novelty. A repeated habit is advice, never a veto.
"""

from __future__ import annotations

import re
from collections import Counter
from urllib.parse import urlsplit

# Requirements describe evidence to obtain, not evidence inferred from a URL.
# Routes are editorial choices, not compulsory headings or paragraph counts.
ROUTES = {
    "decision_path": {
        "name": "按条件走到下一步",
        "types": ("troubleshooting", "guide", "tutorial"),
        "gain": "让遇到具体状况的读者知道下一步做什么",
        "sections": ["先辨认自己的条件", "按条件选择动作及核对依据", "无效时停在哪里"],
        "needs": "可核对的操作条件；没有实测就写验证办法，不写验证成功",
        "entry": "直接给出症状和适用范围，不先报社区热度",
        "ending": "停在下一步操作或停止条件，不追加泛泛的互动问题",
        "images": "条件所在界面、操作位置、结果判据；没有对应图片就列缺口",
    },
    "state_walkthrough": {
        "name": "沿一个场景还原变化",
        "types": ("mechanism", "troubleshooting", "tutorial"),
        "gain": "把抽象规则落到一个可追踪的过程",
        "sections": [
            "交代初始条件",
            "对应的规则及出处",
            "逐步说明动作与状态变化",
            "用反例划出边界",
        ],
        "needs": "规则原文及场景条件；假设示例必须标明是假设，不能伪装实测",
        "entry": "从有来源的具体场景进入，不写‘我翻了很多帖子’",
        "ending": "落到规则何时有效、何时不能据此判断",
        "images": "同一场景的关键状态或规则原文，对应解释而非通用宣传图",
    },
    "claim_check": {
        "name": "核对一条流传说法",
        "types": ("investigation", "debate", "mechanism"),
        "gain": "区分原话、可证实部分和推测",
        "sections": ["原话及核对目标", "逐条核对依据与缺口，形成修正后的表述"],
        "needs": "原始说法和可追溯依据；来源互相转载不能算独立印证",
        "entry": "直接列出要核对的命题，不借评论数制造冲突",
        "ending": "给出可确认的窄结论，证据不够时保留未知",
        "images": "原文上下文、对应证据或标注图，写明它各自能证明什么",
    },
    "conditional_comparison": {
        "name": "在同一条件下比较",
        "types": ("guide", "debate", "update", "roundup", "review"),
        "gain": "解释不同选择或结论适用于谁",
        "sections": ["固定比较前提", "逐项对照证据", "各自付出什么代价", "哪些条件会改变选择"],
        "needs": "可比对象和共同维度；没有同条件资料不得给出性能排名",
        "entry": "先交代读者的决策条件，避免先给总评",
        "ending": "给出带条件的选择，允许暂时无法比较",
        "images": "相同前提下的对照，保留版本、参数与出处",
    },
    "change_trace": {
        "name": "追踪一项变化",
        "types": ("update", "investigation", "news"),
        "gain": "分清已经改变、声称改变和尚未验证的部分",
        "sections": ["变化前的具体问题", "按时间核对记录", "对当前行动的影响与未知"],
        "needs": "带日期或版本的前后资料；只有更新说明时不能声称实测改善",
        "entry": "从一项明确变化及时间进入，不罗列整份更新日志",
        "ending": "停在当前能执行的行动和仍需观察的指标",
        "images": "前后版本记录或可比画面，不能用不同条件假装前后对照",
    },
    "evidence_boundary": {
        "name": "把结论的边界说清楚",
        "types": ("investigation", "debate", "mechanism", "guide", "essay", "review"),
        "gain": "回答现有材料究竟够不够支持一个判断",
        "sections": ["先给能确认的窄结论及依据", "解释哪些缺口阻止结论继续扩大"],
        "needs": "至少一条有出处的具体事实；结论必须收窄到它能支持的范围",
        "entry": "用带条件的答案开门见山",
        "ending": "写清补到什么证据才会改变判断，不强行升华或站队",
        "images": "直接支撑结论的材料、条件或缺口，不让图片冒充验证",
    },
    "chronicle": {
        "name": "沿事件或场景展开",
        "types": ("news", "narrative", "review"),
        "gain": "看清变化或观察如何发生，而不是逐段讲抽象规则",
        "sections": ["具体时间或场景", "沿材料推进事件与观察", "落到变化或留下的问题"],
        "needs": "可追溯事件、原文或用户提供的真实记录；不补想象的现场、对话和个人经历",
        "entry": "进入有材料依据的具体时刻，不先概括整篇",
        "ending": "停在事件后果或观察本身，不强行总结成机制和结论",
        "images": "对应时间或场景的材料图；没有图也可清楚叙述，不制造现场证据",
    },
    "curated_collection": {
        "name": "按用途组织一组合集",
        "types": ("roundup", "guide", "news"),
        "gain": "让读者按需求找到各条目的不同用途",
        "sections": ["说明收录范围与筛选依据", "各条目交代独有信息与条件", "按场景整理取舍"],
        "needs": "逐条可核对的材料；可少列几项，不能为凑数量虚构功能、排名或推荐理由",
        "entry": "给出这份合集帮助解决的需求，而非统一总评",
        "ending": "留给读者清楚的使用路径，不必给每项打分或选唯一赢家",
        "images": "与具体条目有关的界面或出处，不用无关海报填满条目",
    },
    "close_reading": {
        "name": "从具体观察写评析",
        "types": ("review", "essay", "narrative"),
        "gain": "把作品或产品的观察与解释联系起来，让读者判断是否认同",
        "sections": ["一个具体片段或观察", "以材料展开解释", "交代判断与局限"],
        "needs": "作品原文、具体片段、文档或用户真实体验；说明哪些是事实、哪些是解读，不冒充测评",
        "entry": "从值得讨论的细节进入，不默认以好坏总评开头",
        "ending": "收在有依据的判断、余味或反问，按作品目的决定",
        "images": "说明观察的画面、摘录或界面，遵守出处和使用条件",
    },
}


def prose(markdown: str) -> list[str]:
    text = re.sub(r"```[^\n]*\n[\s\S]*?```", "", markdown)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[cube_[^\]]+\]", "", text)
    parts = []
    for part in re.split(r"\n\s*\n", text):
        lines = [line for line in part.splitlines() if not re.match(r"^\s{0,3}#{1,6}\s", line)]
        value = re.sub(r"[*_`]+", "", " ".join(lines)).strip()
        if value and not re.fullmatch(r"[\W_]*喵[~～!！。.\s]*", value):
            parts.append(value)
    return parts


def fingerprint(markdown: str) -> dict:
    parts = prose(markdown)
    opening = " ".join(parts[:3])[:400]
    ending = parts[-1] if parts else ""
    # A source mentioned anywhere is normal. Only the entry window is classified.
    habits = []
    if re.search(r"社区|高赞帖|热帖|热搜|评论.{0,12}(?:条|最多|最凶)|盒友", opening):
        habits.append("community_lead")
    if re.search(r"我(?:把|盯着|翻|读|看).{0,65}(?:翻|读|看|半天|几遍)", opening):
        habits.append("reading_persona")
    if re.search(r"[？?][喵~～!！。\s]*$", ending) or re.search(
        r"你(?:们)?.{1,60}还是.{1,35}[喵~～。\s]*$", ending
    ):
        habits.append("question_end")
    # A late rating roll-call is an observable habit, not proof of irrelevance.
    badges = []
    for part in parts[len(parts) // 2 :]:
        found = set(
            token.lower()
            for token in re.findall(
                r"(?<![A-Za-z])(?:MC|OC|GS)(?=\s*\d)|(?<![A-Za-z])(?:IGN|Steam|Eurogamer)(?![A-Za-z])",
                part,
                re.IGNORECASE,
            )
        )
        if len(found) >= 2:
            badges.append(part[:200])
    if badges:
        habits.append("late_ratings")
    return {
        "habits": habits,
        "opening": opening[:200],
        "ending": ending[:240],
        "rating_examples": badges[:1],
    }


HABITS = {
    "community_lead": (
        "从社区声音切入",
        "试着直接给出具体场景、带条件的答案或待核对命题；社区观点留在它真正提供证据的位置",
    ),
    "reading_persona": (
        "以翻帖、盯着看等阅读动作制造叙事",
        "删掉重复的阅读表演，把篇幅交给事实、条件和推理；不要补写不存在的阅读经历",
    ),
    "question_end": (
        "问句收尾",
        "按本篇用途停在下一步、适用边界、已确认结论或待补证据；确有具体讨论需求时再提问",
    ),
    "late_ratings": (
        "后半篇再次罗列评分或平台数字",
        "核对这些数字是否支撑本篇核心问题；评论热度、总人数和总死亡数不能替代机制或分阶段证据",
    ),
}


def audit(history: list[dict], markdown: str | None = None) -> dict:
    """Use the five most recent published texts, never draft mtimes or titles alone."""
    recent = sorted(history, key=lambda x: x["published_at"], reverse=True)[:5]
    samples = [(old, fingerprint(old["markdown"])) for old in recent]
    counts = Counter(h for _, fp in samples for h in fp["habits"])
    patterns = []
    for key, (label, suggestion) in HABITS.items():
        if counts[key] < 2 or counts[key] / len(recent) < 0.6:
            continue
        examples = []
        for old, fp in samples:
            if key not in fp["habits"]:
                continue
            text = (
                fp["ending"]
                if key == "question_end"
                else (fp["rating_examples"][0] if key == "late_ratings" else fp["opening"])
            )
            examples.append({"link_id": old["link_id"], "title": old["title"], "text": text})
        patterns.append(
            {
                "id": key,
                "label": label,
                "count": counts[key],
                "examples": examples,
                "suggestion": suggestion,
            }
        )
    draft = fingerprint(markdown) if markdown is not None else None
    warnings = []
    if draft:
        for pattern in patterns:
            if pattern["id"] in draft["habits"]:
                warnings.append(
                    f"写法习惯：最近 {len(recent)} 篇中 {pattern['count']} 篇{pattern['label']}，"
                    f"本稿再次出现。{pattern['suggestion']}"
                )
    return {
        "history_count": len(recent),
        "patterns": patterns,
        "draft": draft,
        "warnings": warnings,
        "method": "仅识别文本可观察的写法习惯；不证明语义重复、事实正确或图片内容相同。保留语气，不强制轮换。",
    }


def planning_context(history: list[dict]) -> dict:
    """Bounded excerpts let an editor/model see habits hidden by changed headings."""
    recent = sorted(history, key=lambda x: x["published_at"], reverse=True)[:5]
    report = audit(recent)
    return {
        "sample_size": len(recent),
        "habits_to_reconsider": report["patterns"],
        "published": [
            {
                "link_id": x["link_id"],
                "title": x["title"][:120],
                "question": str(x.get("brief", {}).get("question", ""))[:240],
                "conclusion": str(x.get("brief", {}).get("conclusion", ""))[:240],
                "old_evidence_excerpts_not_verified_facts": [
                    p[:240]
                    for p in prose(x["markdown"])
                    if len(p) >= 35 and re.search(r"\d|来源|规则|说明|评测", p)
                ][:4],
                **{k: v for k, v in fingerprint(x["markdown"]).items() if k != "rating_examples"},
            }
            for x in recent
        ],
        "routes": ROUTES,
    }


def rank_cards(cards: list[dict], material: str, limit: int = 4) -> list[dict]:
    """Rank by topic fit, then diversify useful argument orders. No random rotation."""

    def grams(value):
        value = re.sub(r"\W", "", value.lower())
        return {value[i : i + 2] for i in range(len(value) - 1)}

    query = grams(material)
    ranked = []
    for card in cards:
        searchable = " ".join(
            str(card.get(k, "")) for k in ("reader_question", "applicable_when", "article_type")
        )
        score = len(query & grams(searchable))
        if score:
            ranked.append((score, card))
    ranked.sort(key=lambda x: (-x[0], str(x[1].get("link_id", ""))))
    selected, orders = [], set()
    for _, card in ranked:
        order = tuple(card.get("argument_order", []))
        if order in orders:
            continue
        selected.append(card)
        orders.add(order)
        if len(selected) >= limit:
            break
    return selected


def image_identity(url: str) -> str:
    """Heybox serves one asset through several hosts and thumbnail parameters."""
    parsed = urlsplit(url)
    if re.fullmatch(r"imgheybox\d*\.max-c\.com", parsed.hostname or ""):
        match = re.search(r"/[a-f0-9]{32}(?:/|\.)", parsed.path)
        if match:
            return match[0].strip("/.")
    return url


def reused_images(markdown: str, history: list[dict]) -> list[dict]:
    current = {
        image_identity(url) for url in re.findall(r"!\[[^\]]*\]\((https?://[^)]+)\)", markdown)
    }
    matches = []
    for old in history[:20]:
        previous = {
            image_identity(url)
            for url in re.findall(r"!\[[^\]]*\]\((https?://[^)]+)\)", old["markdown"])
        }
        count = len(current & previous)
        if count:
            matches.append({"link_id": old["link_id"], "title": old["title"], "count": count})
    return matches
