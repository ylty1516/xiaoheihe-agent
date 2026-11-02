"""Loopback authoring UI with explicit account actions and durable auto jobs.

Reading a page does not authorize a new writing or publication task. Background
workers resume only previously requested work; remote writes retain their gates.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from pathlib import Path

from aiohttp import web

from xhh_agent.config import Config, load_config
from xhh_agent.protocol.errors import LoginExpired, XhhError
from xhh_agent.protocol.session import SessionStore
from xhh_agent.store.db import Store

from .publishing import list_drafts, preflight, publish
from .state import build_state
from .editorial import editor_action, read_draft

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).with_name("static")
#: 这三个是**只读**动作，走 /api/action。发帖走单独的 /api/publish，多一道确认。
SAFE_ACTIONS = ("doctor", "hot", "poll")


def _session_path(cfg: Config, root: Path) -> Path:
    db_path = Path(cfg.db_path)
    if not db_path.is_absolute():
        db_path = root / db_path
    return db_path.parent / "session.json"


def _make_client(cfg: Config, root: Path):
    from xhh_agent.protocol.client import ProtocolClient

    session = SessionStore(_session_path(cfg, root)).load()
    return ProtocolClient(session, cfg)


async def _action(name: str, cfg: Config, root: Path) -> dict:
    """跑一个安全动作。返回 ``{"ok": bool, "title": str, "lines": [...]}``。"""
    if name == "doctor":
        from xhh_agent.cli.cmd_doctor import run_checks

        client = _make_client(cfg, root)
        try:
            report = await run_checks(client)
        finally:
            await client.close()
        lines = [
            f"{'OK ' if check.ok else 'X  '}{check.name:<10}{check.detail}"
            for check in report.checks
        ]
        return {
            "ok": report.ok,
            "title": "自检通过" if report.ok else "自检没过，别急着发东西",
            "lines": lines,
        }

    if name == "hot":
        client = _make_client(cfg, root)
        try:
            topics = await client.fetch_hot_topics(limit=8)
        finally:
            await client.close()
        return {
            "ok": True,
            "title": f"热搜榜前 {len(topics)} 条",
            "lines": [
                f"{t['index']}. {t['text']}" + (f"  [{t['right_tag']}]" if t["right_tag"] else "")
                for t in topics
            ],
        }

    if name == "poll":
        from xhh_agent.automation.poll import PollRunner

        db_path = Path(cfg.db_path)
        if not db_path.is_absolute():
            db_path = root / db_path
        store = Store(db_path)
        client = _make_client(cfg, root)
        try:
            report = await PollRunner(client, store, cfg).run_once()
        finally:
            await client.close()
            store.close()
        lines = [f"扫描 {report.scanned} / 跳过 {report.skipped} / 入队 {report.queued}"]
        if report.blocked:
            lines.append(f"被闸门拦下：{report.blocked}")
        lines += [f"  {message_id}  {reason}" for message_id, reason in report.reasons[:12]]
        return {"ok": True, "title": "拉了一轮评论", "lines": lines}

    raise ValueError(f"动作 {name} 不在白名单里")


def create_app(root: Path | None = None, cfg: Config | None = None) -> web.Application:
    base = Path(root or Path.cwd()).resolve()
    config = cfg or load_config()

    async def index(_: web.Request) -> web.FileResponse:
        return web.FileResponse(STATIC_DIR / "index.html")

    async def editorial_script(_: web.Request) -> web.FileResponse:
        return web.FileResponse(STATIC_DIR / "editorial.js")

    async def console_style(_: web.Request) -> web.FileResponse:
        return web.FileResponse(STATIC_DIR / "console.css")

    async def background_script(_: web.Request) -> web.FileResponse:
        return web.FileResponse(STATIC_DIR / "effects.js")

    async def persona_script(_: web.Request) -> web.FileResponse:
        return web.FileResponse(STATIC_DIR / "personas.js")

    async def state(request: web.Request) -> web.Response:
        payload = await asyncio.to_thread(build_state, base)
        payload["duty_url"] = request.app["duty_url"]
        return web.json_response(payload)

    async def action(request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            return web.json_response(
                {"ok": False, "title": "请求体不是 JSON", "lines": []}, status=400
            )

        name = str(body.get("name", ""))
        if name not in SAFE_ACTIONS:
            return web.json_response(
                {"ok": False, "title": f"动作 {name} 不在白名单里", "lines": []}, status=403
            )
        try:
            result = await _action(name, config, base)
        except LoginExpired as exc:
            return web.json_response({"ok": False, "title": "会话失效", "lines": [str(exc)]})
        except XhhError as exc:
            return web.json_response({"ok": False, "title": "接口报错", "lines": [str(exc)]})
        except FileNotFoundError as exc:
            return web.json_response({"ok": False, "title": "缺文件", "lines": [str(exc)]})
        except Exception as exc:
            logger.exception("面板动作失败：%s", name)
            return web.json_response(
                {"ok": False, "title": "动作失败", "lines": [f"{type(exc).__name__}: {exc}"]}
            )
        return web.json_response(result)

    async def drafts(_: web.Request) -> web.Response:
        return web.json_response(await asyncio.to_thread(list_drafts, base))

    async def preflight_view(request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            return web.json_response({"ok": False, "error": "请求体不是 JSON"}, status=400)
        result = await asyncio.to_thread(
            preflight, base, str(body.get("file", "")), str(body.get("title", ""))
        )
        return web.json_response(result)

    async def editorial_view(request: web.Request) -> web.Response:
        try:
            if request.method == "GET":
                result = await asyncio.to_thread(read_draft, base, request.query.get("file", ""))
            else:
                if request.content_type != "application/json":
                    raise ValueError("写作操作需要 application/json 请求")
                body = await request.json()
                if not isinstance(body, dict):
                    raise ValueError("请求体必须是 JSON 对象")
                result = await asyncio.to_thread(editor_action, base, body)
        except (OSError, ValueError, UnicodeDecodeError) as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        return web.json_response(result)

    async def publish_view(request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            return web.json_response(
                {"ok": False, "title": "请求体不是 JSON", "lines": []}, status=400
            )
        # 唯一会发出内容的路由：必须显式 confirm，不给开关、不给环境变量后门。
        if body.get("confirm") is not True:
            return web.json_response(
                {"ok": False, "title": "没有确认", "lines": ["发布要带 confirm: true"]},
                status=400,
            )
        topics = body.get("topics") or []
        if not isinstance(topics, list):
            topics = [str(topics)]
        result = await publish(
            base,
            config,
            file_name=str(body.get("file", "")),
            title=str(body.get("title", "")),
            topics=[str(t) for t in topics],
            accept_warnings=bool(body.get("accept_warnings")),
            confirm=True,
        )
        return web.json_response(result)

    @web.middleware
    async def local_mutation(request, handler):
        if request.method not in {"GET", "HEAD"}:
            origin = request.headers.get("Origin")
            if origin and origin != f"{request.scheme}://{request.host}":
                return web.json_response({"ok": False, "error": "只能从本地面板操作"}, status=403)
            if request.path != "/api/images" and request.content_type != "application/json":
                return web.json_response(
                    {"ok": False, "error": "请求须为 application/json"}, status=400
                )
        return await handler(request)

    app = web.Application(middlewares=[local_mutation])
    app["duty_url"] = ""
    app.router.add_get("/", index)
    app.router.add_get("/editorial.js", editorial_script)
    app.router.add_get("/console.css", console_style)
    app.router.add_get("/effects.js", background_script)
    app.router.add_get("/personas.js", persona_script)
    app.router.add_get("/api/state", state)
    app.router.add_get("/api/drafts", drafts)
    app.router.add_post("/api/action", action)
    app.router.add_post("/api/preflight", preflight_view)
    app.router.add_get("/api/editorial", editorial_view)
    app.router.add_post("/api/editorial", editorial_view)
    app.router.add_post("/api/publish", publish_view)
    from .workspace import install_workspace_routes

    install_workspace_routes(app, base, config)
    return app


async def serve(*, host: str = "127.0.0.1", port: int = 8765, root: Path | None = None) -> None:
    """起服务，一直跑到 Ctrl+C。"""
    app = create_app(root)
    app["duty_url"] = f"http://{host}:{port}/"
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    print(f"面板已启动：{app['duty_url']}")
    print("按 Ctrl+C 关闭。")
    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        pass
    finally:
        with contextlib.suppress(Exception):
            await runner.cleanup()
