"""xhh auto：一条命令把面板起起来，并打开浏览器。

这就是 `heihe auto` 背后干的事。它是**启动器**，不是守护进程：
前台跑着，Ctrl+C 就结束，不会在后台偷偷留一个进程。

为什么用线程 open 浏览器：``web.run_app`` 起来了才有页面，先开浏览器会撞空页；
但反过来等 server 完全阻塞再开，就永远开不了。折中是起服务后延迟 0.8 秒开。
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
import webbrowser
from pathlib import Path

from aiohttp import web

from xhh_agent.config import Config
from xhh_agent.webui.app import create_app

DEFAULT_PORT = 8765


def _open_later(url: str, delay: float = 0.8) -> None:
    def worker() -> None:
        import time

        time.sleep(delay)
        # 打不开浏览器不该影响服务，吞掉就好
        with contextlib.suppress(Exception):
            webbrowser.open(url)

    threading.Thread(target=worker, daemon=True).start()


def _find_root(start: Path) -> Path:
    """往上找项目根：带 pyproject.toml 的那一层。找不到就用当前目录。"""
    current = start.resolve()
    for candidate in (current, *current.parents):
        if (candidate / "pyproject.toml").exists():
            return candidate
    return current


async def _serve(cfg: Config, root: Path, port: int, open_browser: bool) -> int:
    app = create_app(root, cfg)
    url = f"http://127.0.0.1:{port}/"
    app["duty_url"] = url

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", port)
    try:
        await site.start()
    except OSError as exc:
        await runner.cleanup()
        print(f"端口 {port} 起不来：{exc}")
        print("换一个端口：xhh auto --port 8766")
        return 1

    print(f"面板：{url}")
    print(f"项目根：{root}")
    print("Ctrl+C 结束。")
    if open_browser:
        _open_later(url)

    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await runner.cleanup()
    return 0


def main(args: object, cfg: Config) -> int:
    root = _find_root(Path(getattr(args, "root", "") or Path.cwd()))
    port = int(getattr(args, "port", DEFAULT_PORT) or DEFAULT_PORT)
    open_browser = not bool(getattr(args, "no_open", False))
    try:
        return asyncio.run(_serve(cfg, root, port, open_browser))
    except KeyboardInterrupt:
        return 0
