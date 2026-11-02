"""Inspect daily tasks without pretending to complete native App actions."""

import asyncio
import json
from pathlib import Path

from xhh_agent.automation.daily import DailyTasks
from xhh_agent.content.editorial import write_json
from xhh_agent.protocol.client import ProtocolClient
from xhh_agent.protocol.session import SessionStore


def main(args, cfg):
    root = Path(args.root or Path.cwd()).resolve()
    database = Path(cfg.db_path)
    session = (database if database.is_absolute() else root / database).parent / "session.json"
    service = DailyTasks(root, lambda: ProtocolClient(SessionStore(session).load(), cfg))
    if args.enable or args.disable:
        write_json(root / ".data/daily-tasks-settings.json", {"enabled": bool(args.enable)})
    report = asyncio.run(service.refresh()) if args.refresh else service.read()
    report["monitor_enabled"] = service.enabled()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["state"] == "blocked" else 0
