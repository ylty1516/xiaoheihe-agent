"""xhh auto：一条命令把面板起起来，并打开浏览器。

这就是 `heihe auto` 背后干的事。它是**启动器**，不是守护进程：
前台跑着，Ctrl+C 就结束，不会在后台偷偷留一个进程。

端口规则（踩过坑之后定的）：

1. 先探测目标端口上是不是**已经有一个自己**。是的话不重复起，
   直接把浏览器指过去——这比报 EADDRINUSE 有用得多。
2. 端口被别的程序占了，就往后找（默认最多试 10 个），并且**说清换了哪个**。
3. 只有全部试完都失败才报错退出。
"""

from __future__ import annotations

import asyncio
import contextlib
import errno
import threading
import webbrowser
from pathlib import Path

import aiohttp
from aiohttp import web

from xhh_agent.config import Config
from xhh_agent.webui.app import create_app

DEFAULT_PORT = 8765
#: 被占用时往后找多少个端口
PORT_SCAN = 10
#: Windows 的 EADDRINUSE 是 10048，Linux/macOS 是 errno.EADDRINUSE
_IN_USE = {errno.EADDRINUSE, 10048}


def _open_later(url: str, delay: float = 0.8) -> None:
    def worker() -> None:
        import time

        time.sleep(delay)
        # 打不开浏览器不该影响服务
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


async def _already_running(port: int, timeout: float = 1.2) -> str:
    """探测该端口上是不是已经有一个值班台。是就返回 URL。"""
    url = f"http://127.0.0.1:{port}/"
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=timeout)
        ) as session, session.get(url + "api/state") as resp:
            if resp.status != 200:
                return ""
            data = await resp.json(content_type=None)
    except (TimeoutError, aiohttp.ClientError, ValueError, OSError):
        return ""
    # 认状态字段，避免把别的服务误判成自己
    return url if isinstance(data, dict) and {"now", "slot", "account"} <= set(data) else ""


async def _serve(cfg: Config, root: Path, port: int, open_browser: bool) -> int:
    running = await _already_running(port)
    if running:
        print(f"面板已经在跑：{running}")
        print("直接用它，没有重复启动。")
        if open_browser:
            _open_later(running, delay=0.2)
        return 0

    last_error = ""
    for candidate in range(port, port + PORT_SCAN):
        app = create_app(root, cfg)
        url = f"http://127.0.0.1:{candidate}/"
        app["duty_url"] = url

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", candidate)
        try:
            await site.start()
        except OSError as exc:
            await runner.cleanup()
            if exc.errno in _IN_USE:
                last_error = f"{candidate} 被占用"
                continue
            print(f"起不来：{exc}")
            return 1

        if candidate != port:
            print(f"端口 {port} 被占用，改用 {candidate}。")
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

    print(f"起不来：从 {port} 开始的 {PORT_SCAN} 个端口都不可用（{last_error}）。")
    print("换一个范围试试：xhh auto --port 9100")
    return 1


def main(args: object, cfg: Config) -> int:
    root = _find_root(Path(getattr(args, "root", "") or Path.cwd()))
    port = int(getattr(args, "port", DEFAULT_PORT) or DEFAULT_PORT)
    open_browser = not bool(getattr(args, "no_open", False))
    try:
        return asyncio.run(_serve(cfg, root, port, open_browser))
    except KeyboardInterrupt:
        return 0
