import time

import pytest

from xhh_agent.cli.cmd_doctor import doctor_main, run_checks

#: 取代原先的 `lambda: int(time.time()) - 300`。
#: 那个 lambda 让 `await client.server_time()` 抛 TypeError 并被吞成
#: "无法获取服务端时间"，导致 skew 比较从未执行——测试是绿的但什么都没测。


def _with_server_time(client, offset_seconds):
    async def _server_time():
        return int(time.time()) + offset_seconds

    client.server_time = _server_time
    return client


async def test_clock_within_tolerance_passes(fake_doctor_client):
    report = await run_checks(_with_server_time(fake_doctor_client, 30))
    clock = next(c for c in report.checks if c.name == "clock")
    assert clock.ok, clock.detail


async def test_clock_skew_beyond_tolerance_fails_with_real_delta(fake_doctor_client):
    """必须断言偏差数值，否则分不清"算过 skew"和"await 抛异常被吞"。"""
    report = await run_checks(_with_server_time(fake_doctor_client, -300))
    clock = next(c for c in report.checks if c.name == "clock")
    assert not clock.ok
    assert "300" in clock.detail, clock.detail


async def test_clock_unknown_server_time_is_not_reported_ok(fake_doctor_client):
    """拿不到服务端时间时必须报"未验证"，不能回退本地时间报 OK（审查 I2）

    一个时间自检在测不到的时候说 OK，比没有自检更糟。
    """

    async def _none():
        return None

    fake_doctor_client.server_time = _none
    report = await run_checks(fake_doctor_client)
    clock = next(c for c in report.checks if c.name == "clock")
    assert not clock.ok
    assert "未验证" in clock.detail or "无法" in clock.detail


async def test_doctor_runs_checks_in_fixed_order(fake_expired_client):
    report = await run_checks(fake_expired_client)
    assert [c.name for c in report.checks] == ["session", "clock", "signature", "inbox"]


async def test_doctor_short_circuits_after_failure(fake_expired_client):
    report = await run_checks(fake_expired_client)
    failed_index = next(i for i, c in enumerate(report.checks) if not c.ok)
    for check in report.checks[failed_index + 1 :]:
        assert not check.ok
        assert "skipped" in check.detail.lower()


async def test_clock_failure_does_not_claim_login_expired(fake_doctor_client):
    """审查 I1：时钟偏移不能被报成"请重新登录"，否则用户会陷入
    "扫码→再自检→还是 3"的死循环，永远看不到"请校时"。"""
    code = await doctor_main(_with_server_time(fake_doctor_client, 600))
    assert code != 3


async def test_doctor_exit_code_is_3_on_expired_session(fake_expired_client):
    assert await doctor_main(fake_expired_client) == 3


async def test_doctor_exit_code_is_0_when_all_pass(fake_doctor_client):
    assert await doctor_main(fake_doctor_client) == 0
