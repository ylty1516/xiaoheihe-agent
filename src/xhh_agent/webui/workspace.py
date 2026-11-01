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
from xhh_agent.protocol.errors import XhhError

from .editorial import archived_drafts, draft_path, read_draft
from .media import MAX_IMAGE_BYTES, media_path, render_preview, save_image
from .operations import Operations
from .publishing import list_drafts
from .writer import Writer


def install_workspace_routes(app, root, cfg):
    writer = Writer(root, cfg)
    operations = Operations(root, cfg, writer)

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
            except asyncio.TimeoutError:
                return web.json_response(
                    {"ok": False, "error": "请求超时，请核对结果后再操作"}, status=504
                )
            except (GenerationError, aiohttp.ClientError):
                return web.json_response(
                    {"ok": False, "error": "模型或网络请求没有完成，请核对设置后重试"}, status=502
                )

        return wrapped

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
        return web.json_response(await writer.generate(await body(request)))

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
    app.router.add_post("/api/preview", preview)
    app.router.add_post("/api/images", upload)
    app.router.add_get("/api/media/{name}", image)
    app.router.add_get("/api/export", export)
    app.router.add_get("/api/model", model)
    app.router.add_post("/api/model", model)
    app.router.add_post("/api/generate", generate)
    app.router.add_get("/api/comments", queue)
    app.router.add_post("/api/operate", operate)
    app.router.add_get("/api/note", note)
    app.router.add_post("/api/note/analyze", analyze_note)
