"""HTTP routes for local authoring, AI tasks and explicitly requested account work."""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from urllib.parse import quote

import aiohttp
from aiohttp import web

from xhh_agent.automation.generator import GenerationError
from xhh_agent.content.diversity import audit
from xhh_agent.content.editorial import load_history, save_writing_card
from xhh_agent.content.persona import SCENES, Personas, digest, reference, validate
from xhh_agent.content.preferences import load_preferences, save_preferences
from xhh_agent.automation.daily import DailyTasks
from xhh_agent.content.writing import options
from xhh_agent.protocol.errors import XhhError

from .autopilot import Autopilot
from .editorial import archived_drafts, draft_path, read_draft
from .experiments import execute
from .media import MAX_IMAGE_BYTES, media_path, render_preview, save_image
from .operations import Operations
from .publishing import list_drafts
from .research import fetch_sources
from .writer import Writer


def install_workspace_routes(app, root, cfg):
    writer = Writer(root, cfg)
    operations = Operations(root, cfg, writer)
    autopilot = Autopilot(root, writer, operations)
    personas = Personas(root)
    watcher = None
    daily_watcher = None
    daily_tasks = DailyTasks(root, operations.client)

    async def startup(_):
        nonlocal watcher, daily_watcher
        watcher = asyncio.create_task(autopilot.watch())
        daily_watcher = asyncio.create_task(daily_tasks.watch())

    async def cleanup(_):
        if watcher:
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)
        await autopilot.close()
        if daily_watcher:
            daily_watcher.cancel()
            await asyncio.gather(daily_watcher, return_exceptions=True)

    app.on_startup.append(startup)
    app.on_cleanup.append(cleanup)

    async def body(request):
        if request.content_type != "application/json":
            raise ValueError("请求须为 JSON")
        origin = request.headers.get("Origin")
        if origin and origin != f"{request.scheme}://{request.host}":
            raise ValueError("只能从本地面板操作")
        data = await request.json()
        if not isinstance(data, dict):
            raise ValueError("请求内容须为对象")
        return data

    def route(handler):
        async def wrapped(request):
            try:
                return await handler(request)
            except (ValueError, OSError, XhhError) as exc:
                return web.json_response({"ok": False, "error": str(exc)}, status=400)
            except TimeoutError:
                return web.json_response(
                    {"ok": False, "error": "请求超时，请核对结果后再操作"}, status=504
                )
            except (GenerationError, aiohttp.ClientError):
                return web.json_response(
                    {"ok": False, "error": "模型或网络请求没有完成，请核对设置后重试"}, status=502
                )

        return wrapped

    @route
    async def writing_options(_):
        return web.json_response({"ok": True, **options(), "defaults": load_preferences(root)})

    @route
    async def daily_status(request):
        if request.method == "POST":
            await body(request)
            report = await daily_tasks.refresh()
        else:
            report = daily_tasks.read()
        return web.json_response({"ok": True, **report})

    @route
    async def authoring_settings(request):
        settings = (
            load_preferences(root)
            if request.method == "GET"
            else save_preferences(root, await body(request))
        )
        return web.json_response({"ok": True, **settings})

    @route
    async def library(_):
        def read():
            history = load_history(root)
            return {
                "ok": True,
                "drafts": list_drafts(root),
                "archived": archived_drafts(root),
                "published": [
                    {k: x.get(k, "") for k in ("link_id", "title", "published_at")} for x in history
                ],
                "diversity": audit(history),
            }

        return web.json_response(await asyncio.to_thread(read))

    @route
    async def preview(request):
        data = await body(request)
        return web.json_response(
            {"ok": True, "html": await asyncio.to_thread(render_preview, data.get("markdown", ""))}
        )

    @route
    async def upload(request):
        origin = request.headers.get("Origin")
        if origin and origin != f"{request.scheme}://{request.host}":
            raise ValueError("只能从本地面板上传")
        if not request.content_type.startswith("multipart/"):
            raise ValueError("请选择图片文件")
        multipart = await request.multipart()
        field = await multipart.next()
        if field is None or not field.filename:
            raise ValueError("没有收到图片")
        content = bytearray()
        while chunk := await field.read_chunk():
            content.extend(chunk)
            if len(content) > MAX_IMAGE_BYTES:
                raise ValueError("图片超过 8 MB")
        return web.json_response(await asyncio.to_thread(save_image, root, bytes(content)))

    @route
    async def image(request):
        path = media_path(root, request.match_info["name"])
        if not path.is_file():
            raise ValueError("图片不存在")
        return web.FileResponse(path, headers={"X-Content-Type-Options": "nosniff"})

    @route
    async def export(request):
        name = request.query.get("file", "")
        path = draft_path(root, name)
        if not path.is_file():
            raise ValueError("稿件不存在")
        data = read_draft(root, name)
        text = data["markdown"]
        if data["title"] and not text.lstrip().startswith("# " + data["title"]):
            text = "# " + data["title"] + "\n\n" + text
        return web.Response(
            text=text,
            content_type="text/markdown",
            headers={"Content-Disposition": "attachment; filename*=UTF-8''" + quote(path.name)},
        )

    @route
    async def model(request):
        if request.method == "GET":
            return web.json_response({"ok": True, **writer.public()})
        data = await body(request)
        return web.json_response({"ok": True, **writer.configure(data)})

    @route
    async def generate(request):
        data = await body(request)
        data.pop("_persona_snapshot", None)
        return web.json_response(await writer.generate(data))

    @route
    async def persona_cards(request):
        if request.method == "GET":
            if request.query.get("summary") == "1":
                snapshot = personas.get()
                return web.json_response(
                    {
                        "ok": True,
                        "active": {**reference(snapshot), "name": snapshot["card"]["name"]},
                    }
                )
            if request.query.get("list") == "1":
                snapshot = personas.get()
                return web.json_response(
                    {
                        "ok": True,
                        "items": personas.list(),
                        "active": {**reference(snapshot), "name": snapshot["card"]["name"]},
                    }
                )
            if request.query.get("export"):
                fmt = request.query["export"]
                return web.json_response(
                    {
                        "ok": True,
                        "card": personas.export(request.query.get("id"), fmt),
                        "omitted": ["scenes", "examples.avoid"] if fmt == "astrbot" else [],
                    }
                )
            snapshot = personas.get(request.query.get("id"))
            return web.json_response(
                {
                    "ok": True,
                    "snapshot": snapshot,
                    "items": personas.list(),
                    "revisions": personas.revisions(snapshot["card"]["id"]),
                    "default_scenes": SCENES,
                }
            )
        data = await body(request)
        action = data.get("action")
        if action == "save":
            result = personas.save(
                data.get("card"),
                data.get("expected_revision"),
                activate=data.get("activate") is True,
            )
        elif action == "import":
            result = personas.import_card(data.get("card"))
        elif action == "activate":
            result = personas.activate(data.get("id"))
        elif action == "rollback":
            result = personas.rollback(
                data.get("id"), data.get("revision"), data.get("expected_revision")
            )
        else:
            raise ValueError("人设操作无效")
        return web.json_response({"ok": True, "snapshot": result})

    @route
    async def persona_preview(request):
        data = await body(request)
        material = data.get("material", "")
        if not isinstance(material, str) or not 1 <= len(material.strip()) <= 10000:
            raise ValueError("请提供1至10000字的相同试写材料")
        card = validate(data.get("card"))
        edited = {"card": card, "revision": 0, "digest": digest(card)}
        saved = (
            personas.get(card["id"])
            if any(x["id"] == card["id"] for x in personas.list())
            else personas.get()
        )
        results = []
        scene = data.get("scene", "short")
        if not isinstance(scene, str) or scene not in SCENES:
            raise ValueError("请选择有效试写场景")
        for label, snapshot in (("已保存版本", saved), ("当前编辑版本（未保存）", edited)):
            result = await writer.generate(
                {
                    "mode": "write",
                    "material": material,
                    "profile": "short" if scene in {"short", "comment"} else "flexible",
                    "persona_scene": scene,
                    "subject": "auto",
                    "genre": "essay",
                    "_persona_snapshot": snapshot,
                }
            )
            results.append(
                {
                    "label": label,
                    "text": result["text"],
                    "persona": reference(snapshot),
                    "voice_notes": result.get("voice_notes", []),
                }
            )
        return web.json_response({"ok": True, "results": results})

    @route
    async def jobs(request):
        if request.method == "GET":
            job_id = request.query.get("id")
            return web.json_response(
                {
                    "ok": True,
                    **({"job": autopilot.read(job_id)} if job_id else {"items": autopilot.list()}),
                }
            )
        data = await body(request)
        if data.get("action", "start") == "start":
            job = autopilot.create(data)
        elif data.get("action") == "resume":
            job = autopilot.read(data.get("id"))
            task = autopilot.tasks.get(job["id"])
            if task and not task.done():
                raise ValueError("任务正在运行，无需重复继续")
            if job["state"] in {"published", "publishing", "cancelled", "uncertain", "skipped"}:
                raise ValueError("任务已结束或结果待核对，不能重复继续")
            for key, upper in (("max_model_calls", 30), ("max_seconds", 1800)):
                if key in data:
                    if type(data[key]) is not int or not 1 <= data[key] <= upper:
                        raise ValueError("追加预算超出范围")
                    job[key] = data[key]
            if job.get("control") == "pause":
                job.pop("control", None)
            autopilot.update(job, job["state"], "按用户要求继续")
        elif data.get("action") in {"pause", "cancel"}:
            job = await autopilot.control(data.get("id"), data["action"])
            return web.json_response({"ok": True, "job": job})
        elif data.get("action") == "feedback":
            return web.json_response({"ok": True, "card": await autopilot.feedback(data.get("id"))})
        else:
            raise ValueError("不支持的自动任务操作")
        autopilot.launch(job["id"])
        return web.json_response({"ok": True, "job": job})

    @route
    async def desk(request):
        if request.method == "GET":
            event = request.query.get("event", "")
            if event:
                return web.json_response({"ok": True, "items": autopilot.desk.context(event)})
            return web.json_response({"ok": True, **autopilot.desk.overview()})
        data = await body(request)
        if data.get("action") == "experiment":
            result = await execute(root, data.get("recipe"))
            return web.json_response(
                {
                    "ok": True,
                    "card": autopilot.desk.put(
                        {**result, "event": data.get("event") or "环境验证"}
                    ),
                }
            )
        if data.get("action") == "fetch":
            sources = await fetch_sources(data.get("provider"), data.get("key"))
            cards = [
                autopilot.desk.put({**source, "event": data.get("event") or data.get("key")})
                for source in sources
            ]
            return web.json_response({"ok": True, "items": cards})
        if data.get("kind") in {"article", "feedback", "image"}:
            raise ValueError("这类记录由实际任务写入")
        card = autopilot.desk.put(
            {**data, "provenance": "user_provided", "verification": "用户提供的材料，未独立验证"}
        )
        return web.json_response({"ok": True, "card": card})

    @route
    async def queue(_):
        return web.json_response({"ok": True, "items": await asyncio.to_thread(operations.queue)})

    @route
    async def operate(request):
        return web.json_response(await operations.action(await body(request)))

    def read_note(name):
        if Path(name).name != name or any(c in name for c in "/\\:") or not name.endswith(".md"):
            raise ValueError("笔记名称无效")
        folder = (root / "notes/study").resolve()
        path = folder / name
        if path.resolve().parent != folder:
            raise ValueError("笔记路径无效")
        text = path.read_text(encoding="utf-8")[:100_000]
        match = re.search(r"## 正文\s*```text\n([\s\S]*?)\n```", text)
        return path, match[1][:30_000] if match else text[:30_000]

    @route
    async def note(request):
        _, text = await asyncio.to_thread(read_note, request.query.get("name", ""))
        return web.json_response({"ok": True, "text": text})

    @route
    async def analyze_note(request):
        data = await body(request)
        path, text = await asyncio.to_thread(read_note, str(data.get("name", "")))
        match = re.fullmatch(r"\d{4}-\d{2}-\d{2}-([A-Za-z0-9_-]+)", path.stem)
        if not match:
            raise ValueError("笔记缺少可追溯的帖子 ID")
        response = await writer.generate(
            {"mode": "study", "material": "请拆解这篇文章的写法", "markdown": text}
        )
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", response["text"].strip())
        try:
            card = json.loads(raw)
            if not isinstance(card, dict):
                raise ValueError("不是对象")
        except ValueError as exc:
            raise ValueError("模型没有返回有效写法卡，原始笔记已保留") from exc
        card["link_id"] = match[1]
        card["source_url"] = "https://www.xiaoheihe.cn/app/bbs/link/" + match[1]
        await asyncio.to_thread(save_writing_card, root, card)
        return web.json_response({"ok": True, "card": card})

    app.router.add_get("/api/library", library)
    app.router.add_get("/api/writing-options", writing_options)
    app.router.add_post("/api/preview", preview)
    app.router.add_post("/api/images", upload)
    app.router.add_get("/api/media/{name}", image)
    app.router.add_get("/api/export", export)
    app.router.add_get("/api/model", model)
    app.router.add_post("/api/model", model)
    app.router.add_post("/api/generate", generate)
    app.router.add_get("/api/autopilot", jobs)
    app.router.add_get("/api/desk", desk)
    app.router.add_get("/api/authoring-settings", authoring_settings)
    app.router.add_get("/api/daily-tasks", daily_status)
    app.router.add_post("/api/daily-tasks", daily_status)
    app.router.add_post("/api/authoring-settings", authoring_settings)
    app.router.add_get("/api/personas", persona_cards)
    app.router.add_post("/api/personas", persona_cards)
    app.router.add_post("/api/personas/preview", persona_preview)
    app.router.add_post("/api/desk", desk)
    app.router.add_post("/api/autopilot", jobs)
    app.router.add_get("/api/comments", queue)
    app.router.add_post("/api/operate", operate)
    app.router.add_get("/api/note", note)
    app.router.add_post("/api/note/analyze", analyze_note)
