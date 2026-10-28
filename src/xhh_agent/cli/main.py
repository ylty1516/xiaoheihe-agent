"""命令行入口。

P0 阶段尚未实现。当前仅提供命令骨架与状态提示，
确保 pyproject 声明的 entry point 可正常 install 而不报错。
"""

from __future__ import annotations

import argparse
import sys

_STAGES = {
    "login": "P0 · 扫码登录",
    "whoami": "P0 · 会话校验",
    "doctor": "P0 · 自检（签名 / 会话 / 接口连通）",
    "inbox": "P0 · 只读拉取消息与私信",
    "draft": "P1 · Markdown → 草稿",
    "publish": "P1 · 正式发布",
    "poll": "P2/P3 · 跑一轮轮询",
    "queue": "P2/P3 · 审核队列",
}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="xhh",
        description="xiaoheihe-agent 命令行",
        epilog="当前为设计阶段骨架，命令尚未实现。规格见 docs/superpowers/specs/",
    )
    sub = p.add_subparsers(dest="command", metavar="<command>")

    sub.add_parser("login", help="扫码登录并持久化会话")
    sub.add_parser("whoami", help="验证会话是否有效")
    sub.add_parser("doctor", help="自检签名与接口连通性")
    sub.add_parser("inbox", help="只读拉取未读消息（不回复）")

    p_draft = sub.add_parser("draft", help="写入草稿（不发布）")
    p_draft.add_argument("--md", metavar="FILE", help="Markdown 源文件")
    p_draft.add_argument("--title", required=False, help="帖子标题")
    p_draft.add_argument("--tag", type=int, default=11, help="分区 tag（默认 11）")

    p_pub = sub.add_parser("publish", help="正式发布（需 --yes）")
    p_pub.add_argument("--md", metavar="FILE")
    p_pub.add_argument("--title")
    p_pub.add_argument("--tag", type=int, default=11)
    p_pub.add_argument("--yes", action="store_true", help="确认发布")

    p_poll = sub.add_parser("poll", help="执行一轮轮询")
    p_poll.add_argument("--once", action="store_true", help="只跑一轮后退出")
    p_poll.add_argument("--dry-run", action="store_true", help="不发送，只报告将要做什么")

    p_q = sub.add_parser("queue", help="审核队列")
    p_q.add_argument("action", choices=["list", "show", "approve", "edit", "reject"])
    p_q.add_argument("id", nargs="?", help="队列条目 id")

    return p


def _force_utf8_output() -> None:
    """Windows 控制台默认 GBK，中文输出会乱码。

    CLI 的输出会被 agent 直接解析，乱码会导致解析失败，因此在入口处强制 UTF-8。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except (AttributeError, OSError):
            pass


def main(argv: list[str] | None = None) -> int:
    _force_utf8_output()
    args = build_parser().parse_args(argv)

    if not args.command:
        build_parser().print_help()
        return 0

    # 已实现的命令分派到这里（延迟导入，避免 CLI 启动就加载 aiohttp）
    if args.command == "login":
        from xhh_agent.cli.cmd_login import main as login_main
        from xhh_agent.config import load_config

        try:
            cfg = load_config()
        except ValueError as exc:
            print(f"配置错误：{exc}", file=sys.stderr)
            return 2
        return login_main(args, cfg)

    stage = _STAGES.get(args.command, "未规划")
    print(f"命令 `{args.command}` 属于 {stage}，尚未实现。", file=sys.stderr)
    print("设计规格：docs/superpowers/specs/2026-10-28-xiaoheihe-agent-design.md", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
