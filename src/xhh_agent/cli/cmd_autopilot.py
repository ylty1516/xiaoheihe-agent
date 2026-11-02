"""One-shot unattended authoring and the native-image handoff for host agents."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from xhh_agent.webui.autopilot import Autopilot
from xhh_agent.webui.operations import Operations
from xhh_agent.webui.writer import Writer


async def run(args, cfg):
    root = Path(args.root or Path.cwd()).resolve()
    writer = Writer(root, cfg)
    service = Autopilot(root, writer, Operations(root, cfg, writer))
    if args.action == "list":
        result = {"items": service.list()}
    elif args.action in {"status", "images"}:
        job = service.read(args.id)
        result = {"images": service.image_requests(job)} if args.action == "images" else job
    elif args.action == "attach":
        path = Path(args.file)
        if path.stat().st_size > 8 * 1024 * 1024:
            raise ValueError("图片超过 8 MB")
        job = service.attach(args.id, args.image_id, path.read_bytes())
        result = await service.run(job["id"]) if not service.image_requests(job) else job
    elif args.action == "resume":
        result = await service.run(args.id)
    else:
        material = (
            Path(args.material_file).read_text(encoding="utf-8") if args.material_file else ""
        )
        job = service.create(
            {
                "instruction": args.instruction or "",
                "query": args.query,
                "material": material,
                "subject": args.subject,
                "genre": args.genre,
                "profile": args.profile,
                "images": args.images,
                "publish": args.publish,
                "confirm": args.yes,
                **({"topics": args.topic} if getattr(args, "topic", None) else {}),
            }
        )
        result = await service.run(job["id"])
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("state") not in {"failed", "uncertain"} else 1


def main(args, cfg):
    try:
        return asyncio.run(run(args, cfg))
    except (ValueError, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2
