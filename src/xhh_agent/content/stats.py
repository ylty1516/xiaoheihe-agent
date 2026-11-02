"""Shared content presets. Account permissions and publication slots are separate."""

from __future__ import annotations

import json
import re
from .persona import voice_notes
from dataclasses import dataclass
from pathlib import Path

#: 原有 article 长文规格的底线，不用于 short/flexible
#: 2026-10-29 用户下调：1500 -> 1000。原话「现在的用户就是很喜欢长篇大论的，
#: 然后带有情感的或者 1000 字吧」。想改回去只改这一个常量。
MIN_CHARS = 1000
#: 推荐下限：过了硬底线但不到这里，会提示「偏短」。用户偏好长篇，
#: 所以这是建议而不是拦截。
RECOMMENDED_MIN = 1500
#: 舒适区上界，超过就提示拆篇
COMFORT_MAX = 2500
#: 整篇表情上限（voice/emoji.md）
MAX_EMOJI = 6
#: 整篇 `喵~` 上限（voice/profile.md：3–4 处）
MAX_MEOW = 4
#: 配图下限
MIN_IMAGES = 3


@dataclass(frozen=True)
class ContentProfile:
    id: str
    name: str
    min_chars: int
    recommended_min: int
    comfort_max: int
    min_images: int
    strict_style: bool
    writing_hint: str


PROFILES = {
    "article": ContentProfile(
        "article",
        "长文",
        MIN_CHARS,
        RECOMMENDED_MIN,
        COMFORT_MAX,
        MIN_IMAGES,
        True,
        "默认延续长文偏好，目标1500-2500字；材料不足不凑字。用户明确指定篇幅时按本次要求写。",
    ),
    "short": ContentProfile(
        "short",
        "短帖",
        1,
        0,
        800,
        0,
        False,
        "写简洁短帖，直接交代有用信息，不扩成长文；用户指定字数时按要求，无须凑配图。",
    ),
    "flexible": ContentProfile(
        "flexible",
        "按需",
        1,
        0,
        0,
        0,
        False,
        "篇幅、段落与配图按本次要求和材料决定，不预设字数或强制配图。",
    ),
}


def get_profile(value: str = "article") -> ContentProfile:
    if not isinstance(value, str) or value not in PROFILES:
        raise ValueError("内容规格必须是 article（长文）、short（短帖）或 flexible（按需）")
    return PROFILES[value]


def load_profile(path: Path, override: str | None = None) -> ContentProfile:
    """CLI and WebUI use the same saved draft choice; explicit CLI flags win."""
    if override is not None:
        return get_profile(override)
    meta = path.with_suffix(".meta.json")
    if not meta.exists():
        return get_profile()
    try:
        data = json.loads(meta.read_text(encoding="utf-8"))
        return get_profile(data.get("profile", "article") if isinstance(data, dict) else None)
    except (OSError, ValueError) as exc:
        raise ValueError("稿件内容规格读取失败，请检查 .meta.json") from exc


_IMG_MD = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_EMOJI = re.compile(r"\[cube_[^\]]+\]")
_H2 = re.compile(r"^##\s+(.+)$", re.MULTILINE)


def count_body_chars(markdown: str) -> int:
    """正文字数：去掉图片 Markdown、小标题符号、表情代码和所有空白。

    小标题**的文字**仍然计入——它也是读者要读的字。
    """
    text = _IMG_MD.sub("", markdown)
    text = _EMOJI.sub("", text)
    text = re.sub(r"^#+\s*", "", text, flags=re.MULTILINE)
    return len(re.sub(r"\s+", "", text))


def check_post(markdown: str, *, profile: str = "article") -> tuple[list[str], list[str]]:
    """返回 (必须改的问题, 提示)。问题为空才算过。"""
    problems: list[str] = []
    notes: list[str] = []
    rules = get_profile(profile)

    chars = count_body_chars(markdown)
    images = len(_IMG_MD.findall(markdown))
    if chars < rules.min_chars and not (rules.min_chars == 1 and images):
        problems.append(f"正文字数 {chars} < {rules.min_chars}（当前{rules.name}规格）")
    elif chars < rules.recommended_min:
        notes.append(
            f"正文字数 {chars} 过了底线，但不到推荐值 {rules.recommended_min}"
            "（用户偏好长篇，能展开就展开）"
        )
    elif rules.comfort_max and chars > rules.comfort_max:
        notes.append(f"正文字数 {chars} 超过当前规格建议 {rules.comfort_max}，可按需要精简")

    # Natural conjunctions are not evidence of bad writing. Ignore image URLs
    # and inline code; detect repetition of stock phrases as an editorial note.
    prose = _IMG_MD.sub("", markdown)
    prose = re.sub(r"`[^`]*`", "", prose)
    stock = ("综上", "值得注意的是", "总而言之", "不难发现", "由此可见")
    hits = [w for w in stock if prose.count(w) >= 2]
    if hits:
        notes.append(f"套话重复：{'、'.join(hits)}，检查是否可用具体事实替换")
    for issue in voice_notes(markdown):
        notes.append(f"表达提醒：{issue['kind']}「{issue['excerpt']}」；{issue['advice']}")

    emoji_count = len(_EMOJI.findall(markdown))
    style_issues = problems if rules.strict_style else notes
    if emoji_count > MAX_EMOJI:
        style_issues.append(f"表情 {emoji_count} 个 > {MAX_EMOJI}")

    meow = markdown.count("喵~")
    if meow > MAX_MEOW:
        style_issues.append(f"喵~ {meow} 处 > {MAX_MEOW}（核对是否需要精简）")

    if images < rules.min_images:
        problems.append(f"配图 {images} 张 < {rules.min_images}（当前{rules.name}规格）")

    headings = _H2.findall(markdown)
    # 四字整齐排比是模板味的典型信号
    uniform = [h for h in headings if len(h.strip()) == 4]
    if len(uniform) >= 3:
        notes.append(f"小标题都是四字排比（{len(uniform)} 个），改得不工整一点")

    return problems, notes


def summarize(markdown: str) -> dict[str, int]:
    """给 CLI 打印用的统计数字。"""
    return {
        "chars": count_body_chars(markdown),
        "images": len(_IMG_MD.findall(markdown)),
        "emoji": len(_EMOJI.findall(markdown)),
        "meow": markdown.count("喵~"),
        "headings": len(_H2.findall(markdown)),
    }
