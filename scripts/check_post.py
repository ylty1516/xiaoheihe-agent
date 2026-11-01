"""发帖前自检的命令行入口。

    py scripts/check_post.py .data/post.md

规则实现在 `xhh_agent.content.stats`，发布流程（`xhh publish`）用的是同一份，
所以这里只是包装，不要在这里再写一套规则。

不算通过就退出码 1。
"""

from __future__ import annotations

import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from xhh_agent.content.stats import (
    PROFILES,
    check_post,
    load_profile,
    summarize,
)
from xhh_agent.cli.main import _force_utf8_output


def main(argv: list[str] | None = None) -> int:
    _force_utf8_output()
    parser = argparse.ArgumentParser(description="按草稿内容规格检查，默认沿用长文偏好")
    parser.add_argument("file", type=Path)
    parser.add_argument("--profile", choices=PROFILES, default=None)
    args = parser.parse_args(argv)
    path = args.file
    if not path.exists():
        print(f"找不到文件：{path}", file=sys.stderr)
        return 2

    markdown = path.read_text(encoding="utf-8")
    stats = summarize(markdown)
    try:
        rules = load_profile(path, args.profile)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    problems, notes = check_post(markdown, profile=rules.id)

    print(f"文件：{path}")
    print(f"内容规格：{rules.name}；正文字数：{stats['chars']}（下限 {rules.min_chars}）")
    print(f"配图：{stats['images']} 张")
    print(f"表情：{stats['emoji']} 个")
    print(f"喵~：{stats['meow']} 处")
    print(f"小标题：{stats['headings']} 个")

    for note in notes:
        print(f"提示：{note}")
    for problem in problems:
        print(f"[X] {problem}", file=sys.stderr)

    if problems:
        print(f"\n未通过（{len(problems)} 项必须改）。别发。", file=sys.stderr)
        return 1

    print("\n通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
