"""发帖的量化自检：字数、转折词、表情密度、配图数。

规则写在 ``voice/content-strategy.md`` 开头的「硬规则」里，这里是它唯一的
代码实现。**不要在别处再写一份**——两份实现迟早对不上，然后就会出现
"脚本说过了、发布流程说没过"这种事。

``scripts/check_post.py`` 是这些函数的命令行包装。
"""

from __future__ import annotations

import re

#: 正文硬底线（用户钉死，不因篇幅压力放宽）
#: 2026-10-29 用户下调：1500 -> 1000。原话「现在的用户就是很喜欢长篇大论的，
#: 然后带有情感的或者 1000 字吧」。想改回去只改这一个常量。
MIN_CHARS = 1000
#: 推荐下限：过了硬底线但不到这里，会提示「偏短」。用户偏好长篇，
#: 所以这是建议而不是拦截。
RECOMMENDED_MIN = 1500
#: 舒适区上界，超过就提示拆篇
COMFORT_MAX = 2500
#: 转折词 / AI 腔词，一个都不该有
TURN_WORDS = (
    "不过",
    "但是",
    "然而",
    "其实",
    "虽然",
    "说实话",
    "综上",
    "值得注意",
    "此外",
    "因此",
    "总而言之",
)
#: 整篇表情上限（voice/emoji.md）
MAX_EMOJI = 6
#: 整篇 `喵~` 上限（voice/profile.md：3–4 处）
MAX_MEOW = 4
#: 配图下限
MIN_IMAGES = 3
#: 小标题上限，超过像说明书
MAX_HEADINGS = 4

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


def check_post(markdown: str) -> tuple[list[str], list[str]]:
    """返回 (必须改的问题, 提示)。问题为空才算过。"""
    problems: list[str] = []
    notes: list[str] = []

    chars = count_body_chars(markdown)
    if chars < MIN_CHARS:
        problems.append(f"正文字数 {chars} < {MIN_CHARS}（硬规则，不到就不发）")
    elif chars < RECOMMENDED_MIN:
        notes.append(
            f"正文字数 {chars} 过了底线，但不到推荐值 {RECOMMENDED_MIN}"
            "（用户偏好长篇，能展开就展开）"
        )
    elif chars > COMFORT_MAX:
        notes.append(f"正文字数 {chars} 超过舒适区 {COMFORT_MAX}，考虑拆成两篇")

    hits = [w for w in TURN_WORDS if w in markdown]
    if hits:
        problems.append(f"出现转折词/AI 腔词：{'、'.join(hits)}")

    emoji_count = len(_EMOJI.findall(markdown))
    if emoji_count > MAX_EMOJI:
        problems.append(f"表情 {emoji_count} 个 > {MAX_EMOJI}")

    meow = markdown.count("喵~")
    if meow > MAX_MEOW:
        problems.append(f"喵~ {meow} 处 > {MAX_MEOW}（密度高了腻）")

    images = len(_IMG_MD.findall(markdown))
    if images < MIN_IMAGES:
        problems.append(f"配图 {images} 张 < {MIN_IMAGES}")

    headings = _H2.findall(markdown)
    if len(headings) > MAX_HEADINGS:
        notes.append(f"小标题 {len(headings)} 个，超过 {MAX_HEADINGS} 个像说明书")
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
