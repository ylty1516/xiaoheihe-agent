"""xhh doctor：在发出任何内容之前，先暴露会让人翻车的问题。

检查顺序：session → clock → signature → inbox。
前一项失败，后面的标记为 skipped（不执行），避免用失效的会话说出"一切正常"。
"""

from __future__ import annotations

import asyncio
import sys
import time
from dataclasses import dataclass, field

from xhh_agent.cli.cmd_login import session_path
from xhh_agent.config import Config
from xhh_agent.protocol.client import ProtocolClient
from xhh_agent.protocol.errors import LoginExpired, XhhError
from xhh_agent.protocol.session import SessionStore

#: 本地时钟偏差超过这个秒数，签名会被服务端拒绝。
CLOCK_SKEW_TOLERANCE_SECONDS = 120

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_LOGIN_EXPIRED = 3

_CHECK_ORDER = ("session", "clock", "signature", "inbox")


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str = ""


@dataclass(frozen=True)
class DoctorReport:
    checks: list[Check] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)


async def run_checks(client: ProtocolClient) -> DoctorReport:
    checks: list[Check] = []

    def skip_rest(start: str) -> None:
        start_at = _CHECK_ORDER.index(start)
        for name in _CHECK_ORDER[start_at:]:
            checks.append(Check(name, False, "skipped：前序检查失败"))

    # 1. 会话
    if not getattr(client.session, "cookie", ""):
        checks.append(Check("session", False, "无会话，请先运行 'xhh login'"))
        skip_rest("clock")
        return DoctorReport(checks)
    checks.append(Check("session", True, f"heybox_id={client.heybox_id}"))

    # 2. 时钟
    try:
        server_now = await client.server_time()
    except Exception as exc:  # noqa: BLE001 - 时钟检查失败原因不影响后续判定
        checks.append(Check("clock", False, f"无法获取服务端时间：{type(exc).__name__}"))
        skip_rest("signature")
        return DoctorReport(checks)
    skew = abs(int(server_now) - int(time.time()))
    if skew > CLOCK_SKEW_TOLERANCE_SECONDS:
        checks.append(
            Check(
                "clock",
                False,
                f"本地时钟偏差 {skew}s，超过 {CLOCK_SKEW_TOLERANCE_SECONDS}s，签名会被拒",
            )
        )
        skip_rest("signature")
        return DoctorReport(checks)
    checks.append(Check("clock", True, f"偏差 {skew}s"))

    # 3. 签名（用一次只读请求验证）
    try:
        account = await client.whoami()
    except LoginExpired as exc:
        checks.append(Check("signature", False, str(exc)))
        skip_rest("inbox")
        return DoctorReport(checks)
    except XhhError as exc:
        checks.append(Check("signature", False, f"{type(exc).__name__}: {exc}"))
        skip_rest("inbox")
        return DoctorReport(checks)
    checks.append(Check("signature", True, f"验签通过（{account.heybox_id}）"))

    # 4. 收件箱
    try:
        page = await client.fetch_inbox(limit=5)
    except XhhError as exc:
        checks.append(Check("inbox", False, f"{type(exc).__name__}: {exc}"))
        return DoctorReport(checks)
    checks.append(Check("inbox", True, f"{len(page.items)} 条消息"))

    return DoctorReport(checks)


async def doctor_main(client: ProtocolClient) -> int:
    report = await run_checks(client)
    for check in report.checks:
        mark = "OK  " if check.ok else "FAIL"
        print(f"{mark} {check.name:<10} {check.detail}")

    if report.ok:
        print("\n自检通过。")
        return EXIT_OK

    if any(c.name in ("session", "signature") and not c.ok for c in report.checks):
        print("\n会话/签名不可用，请运行 'xhh login' 重新登录。", file=sys.stderr)
        return EXIT_LOGIN_EXPIRED

    print("\n自检未通过，见上方 FAIL 项。", file=sys.stderr)
    return EXIT_ERROR


async def _run(cfg: Config) -> int:
    try:
        session = SessionStore(session_path(cfg)).load()
    except LoginExpired as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_LOGIN_EXPIRED

    client = ProtocolClient(session, cfg)
    try:
        return await doctor_main(client)
    finally:
        await client.close()


def main(args: object, cfg: Config) -> int:
    return asyncio.run(_run(cfg))
