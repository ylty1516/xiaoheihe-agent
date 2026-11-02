"""Read-only task monitoring. Completion always comes from the platform."""

import asyncio
from datetime import datetime, timedelta, timezone
import json

from xhh_agent.content.editorial import write_json

SHANGHAI = timezone(timedelta(hours=8))


def today():
    return datetime.now(SHANGHAI).date().isoformat()


def normalize(result):
    groups = result.get("task_list")
    if not isinstance(groups, list):
        raise ValueError("每日任务响应结构变化")
    group = next((g for g in groups if isinstance(g, dict) and g.get("title") == "每日任务"), None)
    raw = group.get("tasks") if group else None
    if not isinstance(raw, list) or not raw:
        raise ValueError("未找到每日任务，不能判断为已完成")
    tasks = []
    for task in raw:
        if not isinstance(task, dict) or not isinstance(task.get("title"), str):
            raise ValueError("每日任务格式变化")
        state, kind = task.get("state"), task.get("type")
        if state not in {"finish", "waiting", "todo"}:
            raise ValueError("每日任务状态无法识别")
        finished = state == "finish"
        reason = "已由平台确认完成" if finished else (
            "签到需要App登录态及原生签名；当前尚未接通" if kind == "sign" else
            "需要实际分享到社交平台，未发送分享消息" if "分享" in task["title"] else
            "需要人工核对任务要求"
        )
        tasks.append({"title": task["title"][:100], "type": str(kind or "")[:50],
                      "state": state, "finished": finished, "reason": reason})
    return {"tasks": tasks, "complete": all(t["finished"] for t in tasks)}


class DailyTasks:
    def __init__(self, root, client_factory):
        self.root, self.client_factory = root, client_factory
        self.lock = asyncio.Lock()

    def path(self):
        return self.root / ".data/daily-tasks" / (today() + ".json")

    def read(self):
        path = self.path()
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {
            "date": today(), "state": "not_checked", "complete": False, "tasks": [],
            "message": "今天尚未检查每日任务",
        }

    def enabled(self):
        path = self.root / ".data/daily-tasks-settings.json"
        return path.exists() and json.loads(path.read_text(encoding="utf-8")).get("enabled") is True

    async def refresh(self):
        async with self.lock:
            date = today()
            client = None
            try:
                client = self.client_factory()
                report = normalize(await asyncio.wait_for(client.fetch_daily_tasks(), timeout=20))
                if today() != date:
                    raise ValueError("检查期间跨日，请重新检查")
                report.update(state="checked", message="只读检查完成；尚未实现App签到或自动分享")
            except asyncio.CancelledError:
                raise
            except Exception:
                report = {"state": "blocked", "complete": False, "tasks": [],
                          "message": "每日任务读取失败，请检查登录或网络；未执行签到或分享"}
            finally:
                if client is not None:
                    await client.close()
            report.update(date=date, checked_at=datetime.now(SHANGHAI).isoformat())
            write_json(self.root / ".data/daily-tasks" / (date + ".json"), report)
            return report

    async def watch(self):
        while True:
            try:
                if self.enabled():
                    await asyncio.wait_for(self.refresh(), timeout=25)
            except asyncio.CancelledError:
                raise
            except Exception:
                pass
            await asyncio.sleep(3600)
