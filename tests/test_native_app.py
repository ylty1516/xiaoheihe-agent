import asyncio
import json
from types import SimpleNamespace

import pytest
from aiohttp.test_utils import TestClient, TestServer

from xhh_agent.automation.native_app import NativeApp, NativeAppError
from xhh_agent.automation.daily import DailyTasks
from xhh_agent.content.editorial import write_json


async def test_bridge_sends_phone_only_over_private_stdin_and_never_argv(tmp_path, monkeypatch):
    import xhh_agent.automation.native_app as module
    request = {}
    launches = []
    class Input:
        def write(self, raw):
            request.update(json.loads(raw))
        async def drain(self):
            pass
    class Output:
        async def readline(self):
            return json.dumps({"id": request["id"], "ok": True, "data": {
                "login_id": "local-only", "phone_hint": "138****0000"
            }}).encode() + b"\n"
    process = SimpleNamespace(stdin=Input(), stdout=Output(), returncode=None)
    async def spawn(*args, **kwargs):
        launches.append((args, kwargs))
        return process
    bridge = NativeApp(tmp_path, lambda: "123")
    bridge.worker.parent.mkdir(parents=True)
    bridge.worker.write_text("// fixture", encoding="utf-8")
    monkeypatch.setattr(module.shutil, "which", lambda name: "node")
    monkeypatch.setattr(module.asyncio, "create_subprocess_exec", spawn)
    result = await bridge.send_code("13800000000")
    assert result["login_id"] == "local-only" and bridge.pending == result
    assert request["phone"] == "13800000000" and request["expected_account"] == "123"
    assert "13800000000" not in str(launches)
    assert launches[0][1]["stderr"] == asyncio.subprocess.DEVNULL


async def test_disconnect_does_not_drop_the_sms_response(tmp_path, monkeypatch):
    bridge = NativeApp(tmp_path)
    started, release = asyncio.Event(), asyncio.Event()
    async def call(*args, **kwargs):
        started.set()
        await release.wait()
        return {"login_id": "persist-in-memory", "phone_hint": "masked"}
    monkeypatch.setattr(bridge, "_call", call)
    task = asyncio.create_task(bridge.send_code("13800000000"))
    await started.wait()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    release.set()
    await asyncio.gather(*list(bridge.calls))
    assert bridge.pending["login_id"] == "persist-in-memory"


async def test_explicit_execution_permission_and_process_lock(tmp_path, monkeypatch):
    bridge = NativeApp(tmp_path)
    with pytest.raises(ValueError, match="授权"):
        await bridge.run()
    calls = []
    async def invoke(*args, **kwargs):
        calls.append(True)
        return {"complete": True}
    monkeypatch.setattr(bridge, "_call", invoke)
    assert (await bridge.run(confirm=True))["complete"]
    import sqlite3
    connection = sqlite3.connect(tmp_path / ".data/app-daily.sqlite")
    connection.execute("BEGIN EXCLUSIVE")
    try:
        with pytest.raises(ValueError, match="另一个"):
            await bridge.run(confirm=True)
    finally:
        connection.close()
    assert calls == [True] and not bridge.running


def native_result():
    return {"date": "2026-11-03", "signed": True, "complete": False, "tasks": [
        {"id": "sign", "title": "签到", "type": "sign", "state": "finish"},
        {"id": "11", "title": "分享评论", "type": "open_window", "state": "waiting"},
    ], "steps": {"11": {"state": "unsupported"}}}


async def test_native_tasks_preserve_unsupported_variants_and_status(tmp_path):
    class App:
        running = False
        def has_session(self):
            return True
        async def run(self, *, confirm):
            assert confirm
            return native_result()
        async def read(self):
            return native_result()
    service = DailyTasks(tmp_path, None, App())
    report = await service.execute(confirm=True)
    assert not report["complete"] and report["tasks"][0]["finished"]
    assert report["tasks"][1]["id"] == "11" and "未验证" in report["tasks"][1]["reason"]
    assert report["execution"]["11"]["state"] == "unsupported"


async def test_start_is_nonblocking_and_repeated_taps_share_one_execution(tmp_path):
    started, release = asyncio.Event(), asyncio.Event()
    class App:
        running = False
        def has_session(self):
            return True
        async def run(self, *, confirm):
            started.set()
            await release.wait()
            return native_result()
    service = DailyTasks(tmp_path, None, App())
    service.start(confirm=True)
    original = service.execution_task
    await started.wait()
    assert service.status()["running"]
    service.start(confirm=True)
    assert service.execution_task is original
    release.set()
    await service.execution_task
    assert not service.status()["running"]


async def test_app_auth_routes_reject_foreign_origin_without_sending_sms(tmp_path, monkeypatch):
    from xhh_agent.webui.app import create_app
    calls = []
    async def send(self, phone):
        calls.append(phone)
        return {"login_id": "local-only", "phone_hint": "masked"}
    monkeypatch.setattr(NativeApp, "send_code", send)
    client = TestClient(TestServer(create_app(tmp_path)))
    await client.start_server()
    try:
        body = {"action": "send_code", "phone": "13800000000"}
        bad = await client.post("/api/app-session", json=body, headers={"Origin": "https://foreign.invalid"})
        assert bad.status >= 400 and not calls
        good = await client.post("/api/app-session", json=body)
        assert (await good.json())["login_id"] == "local-only"
        assert calls == ["13800000000"]
        bad = await client.post("/api/daily-tasks", json={"action": "settings", "auto_execute": True})
        assert bad.status >= 400
        good = await client.post("/api/daily-tasks", json={"action": "settings", "enabled": True, "auto_execute": True, "confirm": True})
        assert (await good.json())["settings"]["auto_execute"] is True
    finally:
        await client.close()


async def test_daily_dialog_assets_are_served_with_javascript_content_type(tmp_path):
    from xhh_agent.webui.app import create_app
    client = TestClient(TestServer(create_app(tmp_path)))
    await client.start_server()
    try:
        response = await client.get("/app-daily.js?v=0.8.0")
        assert response.status == 200 and "javascript" in response.headers["Content-Type"]
        assert "appDailyDialog" in await response.text()
        response = await client.get("/")
        assert "/app-daily.js?v=0.8.0" in await response.text()
    finally:
        await client.close()
