"""Host the loopback UI without a console; Task Scheduler owns this process."""

import argparse
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import socket
import sys
import time
from urllib.error import URLError
from urllib.request import ProxyHandler, Request, build_opener


def service_state(port):
    """Return running / occupied / available without touching account write APIs."""
    try:
        with build_opener(ProxyHandler({})).open(
            Request(f"http://127.0.0.1:{port}/api/state"), timeout=3
        ) as response:
            data = json.loads(response.read(1024 * 1024))
        if isinstance(data, dict) and {"now", "slot", "account"} <= data.keys():
            return "running"
    except (OSError, URLError, ValueError):
        pass
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return "occupied"
    except OSError:
        return "available"


def configure_logging(root):
    folder = root / ".data/logs"
    folder.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(folder / "background.log", maxBytes=2_000_000,
                                  backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)


def serve(root, port):
    from aiohttp import web
    from xhh_agent.webui.app import create_app

    app = create_app(root)
    app["duty_url"] = f"http://127.0.0.1:{port}/"
    web.run_app(app, host="127.0.0.1", port=port, print=None, access_log=None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("invalid port")
    if args.check:
        state = service_state(args.port)
        print(state)
        return 0 if state == "running" else 1
    root = args.root.resolve()
    configure_logging(root)
    previous = None
    while True:
        state = service_state(args.port)
        if state != previous:
            logging.info("Backend %s on loopback port %s", state, args.port)
            previous = state
        if state == "available":
            try:
                serve(root, args.port)
            except Exception:
                # Log the exception type without provider bodies or credentials.
                logging.error("Backend stopped (%s); retrying in 30 seconds", sys.exc_info()[0].__name__)
        time.sleep(30)


if __name__ == "__main__":
    raise SystemExit(main())
