"""Local App authorization, verified execution and cached daily status."""

import asyncio
import getpass
import json
from pathlib import Path
import sys

from xhh_agent.automation.daily import DailyTasks
from xhh_agent.automation.native_app import NativeApp
from xhh_agent.protocol.client import ProtocolClient
from xhh_agent.protocol.session import SessionStore


def main(args, cfg):
    root = Path(args.root or Path.cwd()).resolve()
    database = Path(cfg.db_path)
    session = (database if database.is_absolute() else root / database).parent / "session.json"
    app = NativeApp(root, lambda: SessionStore(session).load().heybox_id)
    service = DailyTasks(root, lambda: ProtocolClient(SessionStore(session).load(), cfg), app)
    if args.auto and not args.yes:
        print("开启自动执行需要 --yes", file=sys.stderr)
        return 2
    if args.enable or args.disable or args.auto:
        service.save_settings(enabled=False if args.disable else True,
                              auto_execute=True if args.auto else False if args.disable else None)

    async def run():
        try:
            if args.action == "login":
                if not sys.stdin.isatty():
                    raise ValueError("请在本机终端直接登录，或打开控制台的每日任务；不要通过聊天发送验证码。")
                print("App登录可能影响手机现有会话。手机号和验证码仅在本机输入。")
                phone = getpass.getpass("手机号（输入不回显）：")
                pending = await app.send_code(phone)
                print("短信已请求：" + pending["phone_hint"])
                code = getpass.getpass("短信验证码：")
                await app.verify_code(pending["login_id"], code)
                return await service.refresh()
            if args.action == "run":
                return await service.execute(confirm=args.yes)
            return await service.refresh() if args.refresh else service.status()
        finally:
            await service.close()
            await app.close()
    try:
        report = asyncio.run(run())
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    report["settings"] = service.settings()
    report["monitor_enabled"] = service.enabled()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["state"] == "blocked" else 0
