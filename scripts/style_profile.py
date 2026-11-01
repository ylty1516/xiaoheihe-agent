"""Layout advice: show FILE or compare FILE [OLD_FILE ...].

Default comparisons use published snapshots, never draft modification times.
Formatting similarity is advisory; use editorial.py review for content checks.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from xhh_agent.cli.main import _force_utf8_output
from xhh_agent.content.editorial import load_history
from xhh_agent.content.style import compare_styles, profile


def main(argv=None) -> int:
    _force_utf8_output()
    args = list(argv if argv is not None else sys.argv[1:])
    if len(args) < 2 or args[0] not in {"show", "compare"}:
        print(__doc__)
        return 2
    try:
        path = Path(args[1])
        markdown = path.read_text(encoding="utf-8")
        if args[0] == "show":
            result = profile(markdown)
        else:
            previous = (
                [{"link_id": p, "markdown": Path(p).read_text(encoding="utf-8")} for p in args[2:]]
                if args[2:]
                else load_history(Path.cwd())
            )
            result = compare_styles(markdown, previous)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
