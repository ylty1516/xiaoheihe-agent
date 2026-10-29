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

    p_login = sub.add_parser("login", help="扫码登录，或用 --cookie 粘贴浏览器 cookie")
    p_login.add_argument(
        "--cookie",
        metavar="STRING",
        default=None,
        help="直接粘贴浏览器 cookie（等价账号密码）；写 '-' 则从标准输入读，避免落进 shell 历史",
    )
    p_login.add_argument(
        "--heybox-id",
        dest="heybox_id",
        metavar="ID",
        default=None,
        help="cookie 里没有 user_heybox_id 时手工指定",
    )
    sub.add_parser("whoami", help="验证会话是否有效")
    sub.add_parser("doctor", help="自检签名与接口连通性")

    p_inbox = sub.add_parser("inbox", help="只读拉取未读消息（不回复）")
    p_inbox.add_argument("-f", "--format", choices=["json", "table"], default="json")
    p_inbox.add_argument("-n", "--limit", type=int, default=20)

    for name, help_text in (
        ("draft", "写入草稿（不公开）"),
        ("publish", "正式发布（需 --yes）"),
    ):
        parser_ref = sub.add_parser(name, help=help_text)
        parser_ref.add_argument("--md", metavar="FILE", help="Markdown 源文件")
        parser_ref.add_argument("--html", metavar="FILE", help="已转换好的 HTML 源文件")
        parser_ref.add_argument("--title", required=False, help="帖子标题")
        parser_ref.add_argument(
            "--tag",
            action="append",
            default=None,
            metavar="ID",
            help="分区 ID（可多次传或逗号分隔）；不给则默认 PC游戏(1)",
        )
        parser_ref.add_argument(
            "--topic",
            action="append",
            default=None,
            metavar="NAME",
            help="分区名字或 ID（可多次传）。游戏帖除了 PC 区还要挂游戏专属分区",
        )
        parser_ref.add_argument("--html-out", dest="html_out", metavar="FILE",
                                help="把转换结果另存一份，便于本地预览")
        parser_ref.add_argument("--yes", action="store_true", help="确认正式发布")
        parser_ref.add_argument("--edit-link", dest="edit_link", default="",
                                help="改已有帖子：传它的 link_id")

    p_poll = sub.add_parser("poll", help="扫描自己帖子下的评论并放入待回复队列")
    p_poll.add_argument("--once", action="store_true", help="只跑一轮后退出")
    p_poll.add_argument("-n", "--limit", type=int, default=20, help="每次拉取的消息条数")
    p_poll.add_argument("--generate-drafts", dest="generate_drafts", action="store_true",
                        help="顺便用模型生成回复草稿（不发送）")

    p_dm = sub.add_parser("dm", help="发一条私信（默认 dry-run）")
    p_dm.add_argument("--to", required=False, metavar="USER_ID", help="收件人 user_id")
    p_dm.add_argument("--text", required=False, help="消息内容")
    p_dm.add_argument("--send", action="store_true", help="真的发送（默认只打印）")
    p_dm.add_argument("--history", action="store_true", help="只看历史，不发消息")
    p_dm.add_argument("-n", "--limit", type=int, default=20, help="历史条数")

    p_q = sub.add_parser("queue", help="审核队列")
    p_q.add_argument("action", choices=["list", "show", "approve", "reject"])
    p_q.add_argument("id", nargs="?", help="队列条目 id")

    p_del = sub.add_parser("delete", help="删除帖子或草稿（不可逆，需 --yes）")
    p_del.add_argument("--link-id", dest="link_id", required=True)
    p_del.add_argument("--draft", action="store_true", help="这是草稿（走下架接口）")
    p_del.add_argument("--yes", action="store_true", help="确认删除")

    p_hot = sub.add_parser("hot", help="看热搜榜（黑盒热议）")
    p_hot.add_argument("-n", "--limit", type=int, default=10, help="取前几条（默认 10）")

    p_tp = sub.add_parser("topic-posts", help="看话题下社区高互动帖在聊什么")
    p_tp.add_argument("query", help="话题关键词，如 GTA6")
    p_tp.add_argument("-n", "--limit", type=int, default=8)
    p_tp.add_argument("--time-range", dest="time_range", default="7d",
                      choices=["7d", "30d", "180d", "360d", ""],
                      help="时间范围，默认本周")

    p_study = sub.add_parser("study", help="逛帖学习：挑高质量帖子存素材（只读）")
    p_study.add_argument("-n", "--count", type=int, default=2, help="挑几篇（默认 2）")
    p_study.add_argument("--notes-dir", dest="notes_dir", default="notes/study")
    p_study.add_argument("--list", action="store_true", help="只看已记录的笔记")

    p_rep = sub.add_parser("reply", help="回复队列里的评论（默认 dry-run）")
    p_rep.add_argument("--queue-id", dest="queue_id", type=int, required=True)
    p_rep.add_argument("--text", required=False, help="回复内容")
    p_rep.add_argument("--generate", action="store_true", help="用模型生成回复内容")
    p_rep.add_argument("--send", action="store_true", help="真的发送")

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
    if args.command in (
        "login",
        "whoami",
        "doctor",
        "inbox",
        "dm",
        "draft",
        "publish",
        "poll",
        "queue",
        "reply",
        "study",
        "delete",
        "hot",
        "topic-posts",
    ):
        from xhh_agent.config import load_config

        try:
            cfg = load_config()
        except ValueError as exc:
            print(f"配置错误：{exc}", file=sys.stderr)
            return 2

        if args.command == "login":
            from xhh_agent.cli.cmd_login import main as handler
        elif args.command == "whoami":
            from xhh_agent.cli.cmd_whoami import main as handler
        elif args.command == "doctor":
            from xhh_agent.cli.cmd_doctor import main as handler
        elif args.command == "dm":
            from xhh_agent.cli.cmd_dm import main as handler
        elif args.command == "draft":
            from xhh_agent.cli.cmd_post import draft_main as handler
        elif args.command == "publish":
            from xhh_agent.cli.cmd_post import publish_main as handler
        elif args.command == "poll":
            from xhh_agent.cli.cmd_reply import poll_main as handler
        elif args.command == "queue":
            from xhh_agent.cli.cmd_reply import queue_main as handler
        elif args.command == "reply":
            from xhh_agent.cli.cmd_reply import reply_main as handler
        elif args.command == "study":
            from xhh_agent.cli.cmd_study import main as handler
        elif args.command == "hot":
            from xhh_agent.cli.cmd_hot import main as handler
        elif args.command == "topic-posts":
            from xhh_agent.cli.cmd_topic import main as handler
        elif args.command == "delete":
            from xhh_agent.cli.cmd_delete import main as handler
        else:
            from xhh_agent.cli.cmd_inbox import main as handler
        return handler(args, cfg)

    stage = _STAGES.get(args.command, "未规划")
    print(f"命令 `{args.command}` 属于 {stage}，尚未实现。", file=sys.stderr)
    print("设计规格：docs/superpowers/specs/2026-10-28-xiaoheihe-agent-design.md", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
