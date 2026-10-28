"""xhh study：逛帖学习。

只读：拉推荐流、挑高质量帖子、把素材存成笔记。不点赞不评论不关注。

    xhh study                # 默认挑 2 篇
    xhh study --count 3      # 挑 3 篇
    xhh study --list         # 看已记的笔记
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from xhh_agent.automation.study import StudyRunner
from xhh_agent.cli.cmd_login import session_path
from xhh_agent.config import Config
from xhh_agent.protocol.client import ProtocolClient
from xhh_agent.protocol.errors import LoginExpired, XhhError
from xhh_agent.protocol.session import SessionStore
from xhh_agent.store.db import Store

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_LOGIN_EXPIRED = 3

DEFAULT_NOTES_DIR = "notes/study"


async def _run(cfg: Config, count: int, notes_dir: str) -> int:
    try:
        session = SessionStore(session_path(cfg)).load()
    except LoginExpired as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_LOGIN_EXPIRED

    client = ProtocolClient(session, cfg)
    store = Store(cfg.db_path)
    try:
        runner = StudyRunner(client, store, notes_dir=notes_dir, count=count)
        result = await runner.run_once()
    except LoginExpired as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_LOGIN_EXPIRED
    except XhhError as exc:
        print(f"逛帖失败：{exc}", file=sys.stderr)
        return EXIT_ERROR
    finally:
        await client.close()
        store.close()

    print(result.summary())
    for note in result.notes:
        print(f"  笔记：{note}")
    if result.notes:
        print("\n读这些笔记，回答文件里的「待分析」问题，把结论沉淀下来。")
    return EXIT_OK


def list_notes(notes_dir: str) -> int:
    base = Path(notes_dir)
    if not base.exists():
        print("还没有笔记。")
        return EXIT_OK
    files = sorted(base.glob("*.md"))
    if not files:
        print("还没有笔记。")
        return EXIT_OK
    print(f"共 {len(files)} 篇笔记：")
    for path in files[-20:]:
        print(f"  {path.name}")
    return EXIT_OK


def main(args: object, cfg: Config) -> int:
    notes_dir = getattr(args, "notes_dir", None) or DEFAULT_NOTES_DIR
    if getattr(args, "list", False):
        return list_notes(notes_dir)
    return asyncio.run(_run(cfg, int(getattr(args, "count", 2) or 2), notes_dir))
