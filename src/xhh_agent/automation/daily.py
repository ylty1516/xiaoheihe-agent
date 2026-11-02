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
            "请先连接App账号后执行签到" if kind == "sign" else
            "尚未执行App分享流程" if "分享" in task["title"] else
            "需要人工核对任务要求"
        )
        tasks.append({"title": task["title"][:100], "type": str(kind or "")[:50],
                      "state": state, "finished": finished, "reason": reason})
    return {"tasks": tasks, "complete": all(t["finished"] for t in tasks)}


class DailyTasks:
    def __init__(self, root, client_factory, app=None):
        self.root, self.client_factory, self.app = root, client_factory, app
        self.lock = asyncio.Lock()
        self.execution_task = None
        self.execution_error = ""

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

    def settings(self):
        path = self.root / ".data/daily-tasks-settings.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def save_settings(self, *, enabled=None, auto_execute=None):
        data = self.settings()
        if enabled is not None:
            data["enabled"] = enabled is True
        if auto_execute is not None:
            data["auto_execute"] = auto_execute is True
        write_json(self.root / ".data/daily-tasks-settings.json", data)
        return data

    def native_report(self, data):
        report = normalize({"task_list": [{"title": "每日任务", "tasks": data["tasks"]}]})
        for task, original in zip(report["tasks"], data["tasks"]):
            task["id"] = original["id"]
            if not task["finished"]:
                task["reason"] = (
                    "等待App签到执行" if original["id"] == "sign" else
                    "等待App分享流程执行；不会发送微信消息" if original["id"] in {"1", "19", "31"} else
                    "该任务类型尚未验证，保留人工处理"
                )
        report.update(date=data["date"], state="checked", app_ready=True,
                      message="已核对App任务进度", checked_at=datetime.now(SHANGHAI).isoformat())
        report["complete"] = bool(data.get("complete", data.get("signed") and report["complete"]))
        if "steps" in data:
            report["execution"] = data["steps"]
        return report

    def status(self):
        running = bool((self.execution_task and not self.execution_task.done()) or
                       (self.app and self.app.running))
        return {**self.read(), "running": running, "execution_error": self.execution_error}

    def start(self, *, confirm=False):
        if confirm is not True or not self.app or not self.app.has_session():
            raise ValueError("请先完成App登录，并明确授权每日任务执行")
        if self.execution_task and not self.execution_task.done():
            return {"accepted": True, "running": True}
        self.execution_error = ""
        async def run():
            try:
                await self.execute(confirm=True)
            except ValueError as exc:
                self.execution_error = str(exc)[:300]
            except Exception:
                self.execution_error = "任务结果未确认，请先刷新核对，不要重复执行。"
        self.execution_task = asyncio.create_task(run())
        return {"accepted": True, "running": True}

    async def close(self):
        if self.execution_task and not self.execution_task.done():
            self.execution_task.cancel()
            await asyncio.gather(self.execution_task, return_exceptions=True)

    async def execute(self, *, confirm=False):
        if confirm is not True or not self.app:
            raise ValueError("请先完成App登录，并明确授权每日任务执行")
        async with self.lock:
            data = await self.app.run(confirm=True)
            report = self.native_report(data)
            write_json(self.root / ".data/daily-tasks" / (data["date"] + ".json"), report)
            return report

    async def refresh(self):
        async with self.lock:
            date = today()
            client = None
            if self.app and self.app.has_session():
                try:
                    report = self.native_report(await self.app.read())
                    write_json(self.root / ".data/daily-tasks" / (report["date"] + ".json"), report)
                    return report
                except asyncio.CancelledError:
                    raise
                except ValueError:
                    # Web state remains readable if the App authorization expires.
                    pass
            try:
                client = self.client_factory()
                report = normalize(await asyncio.wait_for(client.fetch_daily_tasks(), timeout=20))
                if today() != date:
                    raise ValueError("检查期间跨日，请重新检查")
                report.update(state="checked", message="已读取网页版任务；连接App账号后可执行支持的任务")
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
                if self.enabled() and not (self.execution_task and not self.execution_task.done()):
                    if self.settings().get("auto_execute") is True and self.app and self.app.has_session():
                        try:
                            await asyncio.wait_for(self.execute(confirm=True), timeout=260)
                        except (ValueError, asyncio.TimeoutError) as exc:
                            self.execution_error = str(exc)[:300] or "任务执行超时，请先核对状态。"
                            # A read never repeats a write; preserves recovery after uncertainty.
                            await asyncio.wait_for(self.refresh(), timeout=45)
                    else:
                        await asyncio.wait_for(self.refresh(), timeout=45)
            except asyncio.CancelledError:
                raise
            except Exception:
                pass
            await asyncio.sleep(3600)
