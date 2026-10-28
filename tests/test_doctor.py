import time

from xhh_agent.cli.cmd_doctor import doctor_main, run_checks


async def test_doctor_reports_clock_skew(fake_client, monkeypatch):
    """审查重点 #2：本地时钟偏差会让签名直接失效，
    doctor 必须在发任何内容前暴露它"""
    monkeypatch.setattr(fake_client, "server_time", lambda: int(time.time()) - 300)
    report = await run_checks(fake_client)
    assert any(c.name == "clock" and not c.ok for c in report.checks)


async def test_doctor_runs_checks_in_fixed_order(fake_expired_client):
    """四项检查总是全部出现在报告里，前序失败则后续标记 skipped。
    简报原断言 names.index("inbox") 在短路时会抛 ValueError，故改为断言完整序列。"""
    report = await run_checks(fake_expired_client)
    assert [c.name for c in report.checks] == ["session", "clock", "signature", "inbox"]


async def test_doctor_short_circuits_after_failure(fake_expired_client):
    report = await run_checks(fake_expired_client)
    failed_index = next(i for i, c in enumerate(report.checks) if not c.ok)
    # 失败之后的所有检查都不应被真正执行
    for check in report.checks[failed_index + 1 :]:
        assert not check.ok
        assert "skipped" in check.detail.lower()


async def test_doctor_exit_code_is_3_on_expired_session(fake_expired_client):
    assert await doctor_main(fake_expired_client) == 3


async def test_doctor_exit_code_is_0_when_all_pass(fake_doctor_client):
    assert await doctor_main(fake_doctor_client) == 0
