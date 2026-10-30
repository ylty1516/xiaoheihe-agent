"""帖子结构指纹：防止连着几篇长得一模一样。

主人 2026-10-30 的要求：**排版样式要多样，不许每篇都一个模子**。
光在文档里写「要多样」没用，得有个能跑的检查，不然写着写着就回去了。

    py scripts/style_profile.py show   .data/post-a.md
    py scripts/style_profile.py compare .data/post-new.md          # 自动取最近 3 篇旧稿
    py scripts/style_profile.py compare .data/post-new.md .data/post-b.md .data/post-c.md

compare 会逐项对比结构特征，撞了 5 项以上就退出码 1——那就换个写法再发。
只比结构，不比内容；它拦不住「写得无聊」，只拦得住「又写成同一个模板」。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

RECENT_DIR = Path(".data")
RECENT_GLOB = "post-*.md"
RECENT_COUNT = 3
#: 撞车阈值：6 项里撞到这么多就算同一套模板
COLLIDE_THRESHOLD = 4

IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
HEADING_RE = re.compile(r"^#{1,6}\s+(.*)$", re.MULTILINE)
MEOW = "喵"


def _body(markdown: str) -> str:
    text = IMAGE_RE.sub("", markdown)
    text = HEADING_RE.sub("", text)
    return text


def _paragraphs(markdown: str) -> list[str]:
    body = _body(markdown)
    blocks = [b.strip() for b in re.split(r"\n\s*\n", body)]
    return [b for b in blocks if b]


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
            else ("问句" if all(h.endswith(("？", "?")) for h in headings) else "短语")
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


def _recent(exclude: set[Path]) -> list[Path]:
    files = [p for p in RECENT_DIR.glob(RECENT_GLOB) if p not in exclude]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files[:RECENT_COUNT]


def _show(path: Path) -> None:
    prof = profile(path.read_text(encoding="utf-8"))
    print(f"{path}")
    for key, value in prof.items():
        print(f"  {key}: {value}")


def main(argv: list[str] | None = None) -> int:
    args = (argv if argv is not None else sys.argv[1:])
    if not args or args[0] not in {"show", "compare"}:
        print(__doc__, file=sys.stderr)
        return 2

    if args[0] == "show":
        if len(args) < 2:
            print("用法：py scripts/style_profile.py show 稿子.md", file=sys.stderr)
            return 2
        _show(Path(args[1]))
        return 0

    if len(args) < 2:
        print("用法：py scripts/style_profile.py compare 稿子.md [旧稿...]", file=sys.stderr)
        return 2

    new_path = Path(args[1])
    new = profile(new_path.read_text(encoding="utf-8"))
    old_paths = [Path(p) for p in args[2:]] or _recent({new_path})
    if not old_paths:
        print("没有可对比的旧稿，跳过结构撞车检查。")
        return 0

    print(f"新稿：{new_path}")
    for key, value in new.items():
        print(f"  {key}: {value}")

    worst = 0
    for old_path in old_paths:
        old = profile(old_path.read_text(encoding="utf-8"))
        same = [key for key in new if new[key] == old[key]]
        worst = max(worst, len(same))
        flag = "撞车" if len(same) >= COLLIDE_THRESHOLD else "有差异"
        print(f"\n对比 {old_path}：{len(same)}/{len(new)} 项相同 → {flag}")
        print(f"  相同：{'、'.join(same) or '无'}")
        print(f"  不同：{'、'.join(k for k in new if k not in same) or '无'}")

    if worst >= COLLIDE_THRESHOLD:
        print(
            f"\n[X] 结构和旧稿太像（撞了 {worst} 项）。换一种写法："
            "换开头、换小标题密度、换段长节奏、换收尾方式，再跑一次。",
            file=sys.stderr,
        )
        return 1
    print("\n通过：结构和最近几篇不是同一个模子。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
