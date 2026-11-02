"""Private stdio bridge to the local Node App client; secrets never enter argv."""

import asyncio
import contextlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import uuid

from xhh_agent.protocol.errors import XhhError


class NativeAppError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class NativeApp:
    def __init__(self, root, expected_account=lambda: ""):
        self.root, self.expected_account = Path(root), expected_account
        self.worker = self.root / "integrations/heybox-app/lib/worker.mjs"
        self.process = None
        self.lock = asyncio.Lock()
        self.calls = set()
        self.pending = None
        self.running = False

    def has_session(self):
        return (self.root / ".data/app/session.json").is_file()

    def account(self):
        try:
            return self.expected_account()
        except (ValueError, OSError, XhhError):
            return ""

    async def _call(self, action, **fields):
        async with self.lock:
            node = shutil.which("node")
            if not node or not self.worker.is_file():
                raise NativeAppError("runtime_missing", "App组件不可用，请安装Node.js 24及本项目的App模块。")
            if self.process is None or self.process.returncode is not None:
                flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
                self.process = await asyncio.create_subprocess_exec(
                    node, str(self.worker), str(self.root), cwd=self.root,
                    stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL, limit=131072, **flags,
                )
            process = self.process
            request_id = uuid.uuid4().hex
            request = {"id": request_id, "action": action, "expected_account": self.account(), **fields}
            try:
                process.stdin.write((json.dumps(request) + "\n").encode())
                await process.stdin.drain()
                line = await asyncio.wait_for(process.stdout.readline(), 240 if action == "run" else 80)
                response = json.loads(line)
                if response.get("id") != request_id:
                    raise ValueError("invalid response identity")
            except (ValueError, OSError, asyncio.TimeoutError, asyncio.LimitOverrunError):
                await self._stop()
                raise NativeAppError("result_uncertain", "App请求未确认，请刷新状态核对，不要立即重复操作。") from None
            if response.get("ok") is not True:
                # Worker emits only explicitly sanitized, bounded messages.
                raise NativeAppError(str(response.get("code", "request_failed"))[:64],
                                     str(response.get("message", "App请求没有完成"))[:300])
            return response["data"]

    async def _guarded(self, operation):
        # An HTTP disconnect must not discard an in-flight SMS/login response.
        task = asyncio.create_task(operation)
        self.calls.add(task)
        def finished(done):
            self.calls.discard(done)
            if not done.cancelled():
                done.exception()
        task.add_done_callback(finished)
        return await asyncio.shield(task)

    async def status(self):
        if self.running:
            return {"configured": self.has_session(), "running": True,
                    "runtime_ready": True, "pending_login": self.pending}
        try:
            result = await self._call("status")
        except NativeAppError as exc:
            result = {"configured": False, "runtime_ready": False,
                      "code": exc.code, "message": str(exc)}
        return {**result, "running": False, "pending_login": self.pending}

    async def send_code(self, phone):
        if not isinstance(phone, str) or len(phone) > 20:
            raise ValueError("手机号格式不正确")
        async def operation():
            result = await self._call("send_code", phone=phone)
            self.pending = result
            return result
        return await self._guarded(operation())

    async def verify_code(self, login_id, code):
        if not isinstance(login_id, str) or len(login_id) > 64 or not isinstance(code, str) or len(code) > 8:
            raise ValueError("登录编号或验证码格式不正确")
        async def operation():
            result = await self._call("verify_code", login_id=login_id, code=code)
            self.pending = None
            return result
        return await self._guarded(operation())

    async def read(self):
        return await self._guarded(self._call("read"))

    async def run(self, *, confirm=False):
        if confirm is not True:
            raise ValueError("执行每日任务需要明确授权")
        async def operation():
            folder = self.root / ".data"
            folder.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(folder / "app-daily.sqlite", timeout=0)
            try:
                try:
                    connection.execute("BEGIN EXCLUSIVE")
                except sqlite3.OperationalError:
                    raise ValueError("另一个每日任务正在执行，请稍后刷新") from None
                self.running = True
                return await self._call("run", confirm=True)
            finally:
                self.running = False
                connection.close()
        return await self._guarded(operation())

    async def _stop(self):
        process, self.process = self.process, None
        self.pending = None
        if process and process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                process.kill()
            await process.wait()

    async def close(self):
        # Persisted worker intents make restart verification safe.
        for task in list(self.calls):
            task.cancel()
        await asyncio.gather(*self.calls, return_exceptions=True)
        await self._stop()
