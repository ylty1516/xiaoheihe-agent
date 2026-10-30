"""发帖排期守门员的命令行壳子。

规则全在 `xhh_agent.automation.slots` 里，这里只做参数解析和退出码，
不要再在这里写第二份规则。

    py scripts/post_slot.py check     # 0=可以发 3=不许发 4=不在时间窗
    py scripts/post_slot.py record --link-id 195437564
    py scripts/post_slot.py status
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from xhh_agent.automation.slots import (
    DEFAULT_LEDGER,
    MAX_POSTS_PER_DAY,
    MIN_GAP_SECONDS,
    WINDOW_END,
    WINDOW_START,
    load_ledger,
    posts_on,
    record_post,
    slot_state,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="发帖排期守门员")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="现在能不能发")
    rec = sub.add_parser("record", help="登记一篇已发布的帖子")
    rec.add_argument("--link-id", required=True)
    sub.add_parser("status", help="看今天的额度")

    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    now = time.time()

    if args.cmd == "record":
        entry = record_post(str(args.link_id), now=now)
        today = posts_on(load_ledger(DEFAULT_LEDGER), datetime.now())
        print(f"已登记：{entry['link_id']} @ {entry['at']}（今天第 {len(today)} 篇）")
        return 0

    if args.cmd == "status":
        state = slot_state(now=now)
        print(f"今日已发：{state.today_count}/{MAX_POSTS_PER_DAY}")
        for post in posts_on(load_ledger(DEFAULT_LEDGER), datetime.now()):
            print(f"  {post.get('at', '?')}  {post.get('link_id', '?')}")
        if state.next_at:
            print(f"下一篇最早：{state.next_at}")
        print(
            f"时间窗：{WINDOW_START:02d}:00 - {WINDOW_END:02d}:00"
            f"（现在{'在' if state.in_window else '不在'}窗口内）"
        )
        print(f"间隔要求：{MIN_GAP_SECONDS // 3600} 小时")
        return 0

    state = slot_state(now=now)
    print(("可以发" if state.allowed else "跳过") + f"：{state.reason}")
    return state.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
