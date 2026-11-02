"""Portable persona access for agents; never invokes an account operation."""

import json
from pathlib import Path

from xhh_agent.content.persona import Personas, compile_persona, compile_visual, reference
from .cmd_auto import _find_root


def main(args, cfg):
    store = Personas(Path(args.root).resolve() if args.root else _find_root(Path.cwd()))
    try:
        if args.action == "list":
            result = {"items": store.list()}
        elif args.action == "prompt":
            snapshot = store.get(args.id or None, args.revision)
            result = {
                "persona": reference(snapshot),
                "scene": args.scene,
                "prompt": compile_persona(snapshot, args.scene),
            }
        elif args.action == "visual":
            snapshot = store.get(args.id or None, args.revision)
            result = {"persona": reference(snapshot), "prompt": compile_visual(snapshot)}
        elif args.action == "show":
            result = store.get(args.id or None, args.revision)
        elif args.action == "activate":
            result = store.activate(args.id)
        elif args.action == "export":
            result = store.export(args.id or None, args.format)
        elif args.action == "rollback":
            result = store.rollback(args.id, args.revision, args.expected_revision)
        else:
            path = Path(args.file)
            if not path.is_file() or path.stat().st_size > 256000:
                raise ValueError("请选择小于256KB的人设 JSON 文件")
            card = json.loads(path.read_text(encoding="utf-8-sig"))
            result = (
                store.import_card(card)
                if args.action == "import"
                else store.save(card, args.expected_revision)
            )
        print(json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2
