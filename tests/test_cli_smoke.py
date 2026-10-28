import sys

import pytest

from xhh_agent.cli.main import main


def test_all_p0_commands_are_wired():
    for cmd in ("login", "whoami", "doctor", "inbox"):
        with pytest.raises(SystemExit) as exc_info:
            main([cmd, "--help"])
        assert exc_info.value.code == 0, f"{cmd} 未正确接线"


def test_unimplemented_command_returns_2_not_crash():
    """P2 的命令应明确提示未实现，而不是 AttributeError。

    （draft/publish 已在 P1 实现，不能再拿它们当未实现样例。）
    """
    assert main(["poll", "--once"]) == 2


class _FakeStream:
    """没有 reconfigure 方法的流，以及记录调用的流。"""

    def __init__(self, with_reconfigure: bool = True) -> None:
        self.encoding = "gbk"
        self.called_with = None
        if with_reconfigure:
            self.reconfigure = self._reconfigure  # type: ignore[assignment]

    def _reconfigure(self, **kwargs):
        self.called_with = kwargs


def test_force_utf8_output_reconfigures_both_streams(monkeypatch):
    """Windows 控制台默认 GBK，中文输出会乱码，agent 解析会失败（审查重点）"""
    from xhh_agent.cli import main as cli_main

    out, err = _FakeStream(), _FakeStream()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)
    cli_main._force_utf8_output()
    assert out.called_with == {"encoding": "utf-8"}
    assert err.called_with == {"encoding": "utf-8"}


def test_force_utf8_output_tolerates_stream_without_reconfigure(monkeypatch):
    from xhh_agent.cli import main as cli_main

    monkeypatch.setattr(sys, "stdout", _FakeStream(with_reconfigure=False))
    cli_main._force_utf8_output()   # 不应抛异常
