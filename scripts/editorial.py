"""Local editorial workflow; never publishes or calls an LLM.

py scripts/editorial.py init .data/post-new.md
py scripts/editorial.py plan .data/post-new.md
py scripts/editorial.py review .data/post-new.md --require-brief
py scripts/editorial.py import old.md --link-id ID --title TITLE

import is only for an existing, verified public post. It does not publish.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from xhh_agent.cli.main import _force_utf8_output
from xhh_agent.content.editorial import (
    brief_path,
    empty_brief,
    load_brief,
    load_history,
    plan_options,
    record_publication,
    review,
    save_writing_card,
    write_json,
    writing_cards,
)


def main(argv=None) -> int:
    _force_utf8_output()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("init", "plan", "review", "import", "learn", "library"))
    parser.add_argument("file", type=Path, nargs="?")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--require-brief", action="store_true")
    parser.add_argument("--link-id")
    parser.add_argument("--title")
    parser.add_argument("--query", default="")
    args = parser.parse_args(argv)
    try:
        if args.action == "library":
            print(json.dumps(writing_cards(args.root, args.query), ensure_ascii=False, indent=2))
            return 0
        if args.file is None:
            raise ValueError("需要文件路径")
        if args.action == "learn":
            path = save_writing_card(args.root, json.loads(args.file.read_text(encoding="utf-8")))
            print(f"已保存可检索的写法卡：{path}")
            return 0
        if args.action == "init":
            target = brief_path(args.file)
            if target.exists():
                raise ValueError("选题卡已存在，不覆盖")
            write_json(target, empty_brief())
            print(f"选题卡：{target}，填写后再运行 plan")
            return 0
        brief = load_brief(args.file)
        if args.action == "plan":
            result = plan_options(brief or {}, load_history(args.root))
        elif args.action == "import":
            if not args.link_id or not args.title:
                raise ValueError("补录已发布文章需要 --link-id 和 --title")
            record_publication(
                args.root,
                link_id=args.link_id,
                title=args.title,
                markdown=args.file.read_text(encoding="utf-8"),
                brief=brief,
            )
            print("已补录内容快照；未执行发布")
            return 0
        else:
            result = review(
                args.root,
                args.file.read_text(encoding="utf-8"),
                brief,
                require_brief=args.require_brief,
            )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return int(isinstance(result, dict) and bool(result.get("blockers")))
    except (OSError, ValueError) as exc:
        print(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
