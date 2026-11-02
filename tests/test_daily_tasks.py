import json

import pytest
from aiohttp.test_utils import TestClient, TestServer

from xhh_agent.automation.daily import DailyTasks, normalize
from xhh_agent.protocol.client import ProtocolClient
from xhh_agent.protocol.errors import SchemaChanged
from xhh_agent.protocol.session import Session
from xhh_agent.config import load_config


def sample(state="waiting"):
    return {"user": {"userid": "123"}, "task_list": [{"title": "每日任务", "tasks": [
        {"title": "签到", "state": state, "type": "sign"},
        {"title": "分享任意帖子到社交平台", "state": state, "type": "open_window"},
    ]}]}


@pytest.mark.parametrize("state,complete", [("finish", True), ("waiting", False), ("todo", False)])
def test_platform_completion_is_authoritative(state, complete):
    report = normalize(sample(state))
    assert report["complete"] is complete
    if not complete:
        assert "App" in report["tasks"][0]["reason"]
        assert "实际分享" in report["tasks"][1]["reason"]


@pytest.mark.parametrize("result", [{}, {"task_list": []}, {"task_list": [{"title": "每日任务", "tasks": []}]}, sample("unknown")])
def test_empty_or_unknown_state_is_not_complete(result):
    with pytest.raises(ValueError):
        normalize(result)


async def test_protocol_checks_account_and_only_reads(monkeypatch):
    client = ProtocolClient(Session(cookie="secret", heybox_id="123"), load_config())
    result, calls = sample(), []

    async def request(method, url):
        calls.append((method, url.split("?")[0]))
        return {"status": "ok", "result": result}

    monkeypatch.setattr(client, "_request_json", request)
    assert (await client.fetch_daily_tasks())["task_list"]
    result["user"]["userid"] = "456"
    with pytest.raises(SchemaChanged, match="账号不匹配"):
        await client.fetch_daily_tasks()
    assert all(method == "GET" and url.endswith("/task/list_v2/") for method, url in calls)


async def test_monitor_persists_real_states_and_clears_stale_results_on_failure(tmp_path):
    class Client:
        failing = False
        closed = 0

        async def fetch_daily_tasks(self):
            if self.failing:
                raise RuntimeError("cookie=secret")
            return sample("finish")

        async def close(self):
            self.closed += 1

    client = Client()
    service = DailyTasks(tmp_path, lambda: client)
    assert not service.enabled()
    assert service.read()["state"] == "not_checked"
    assert (await service.refresh())["complete"]
    client.failing = True
    assert (await service.refresh())["state"] == "blocked"
    report = service.read()
    assert not report["complete"] and not report["tasks"]
    assert "secret" not in json.dumps(report)
    assert client.closed == 2


async def test_new_day_does_not_reuse_yesterdays_completion(tmp_path, monkeypatch):
    from xhh_agent.automation import daily

    service = DailyTasks(tmp_path, None)
    monkeypatch.setattr(daily, "today", lambda: "2026-11-02")
    service.path().parent.mkdir(parents=True)
    service.path().write_text(json.dumps({"complete": True}), encoding="utf-8")
    monkeypatch.setattr(daily, "today", lambda: "2026-11-03")
    assert not service.read()["complete"]


async def test_api_get_is_cached_and_post_protects_origin(tmp_path, monkeypatch):
    from xhh_agent.webui.app import create_app

    calls = []

    async def refresh(self):
        calls.append(True)
        return {"state": "checked", "complete": False, "tasks": []}

    monkeypatch.setattr(DailyTasks, "refresh", refresh)
    client = TestClient(TestServer(create_app(tmp_path)))
    await client.start_server()
    try:
        assert (await (await client.get("/api/daily-tasks")).json())["state"] == "not_checked"
        assert calls == []
        response = await client.post("/api/daily-tasks", json={}, headers={"Origin": "https://foreign.example"})
        assert response.status >= 400 and not calls
        assert (await (await client.post("/api/daily-tasks", json={})).json())["state"] == "checked"
        assert calls == [True]
    finally:
        await client.close()
