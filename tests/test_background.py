"""No real account writes or long-lived processes are started by these tests."""

import importlib.util
import io
from pathlib import Path

import pytest


@pytest.fixture
def background():
    path = Path(__file__).resolve().parents[1] / "scripts/background.py"
    spec = importlib.util.spec_from_file_location("background_tested", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("kind", ["running", "occupied", "available"])
def test_service_probe_distinguishes_other_programs(background, monkeypatch, kind):
    class Opener:
        def open(self, request, timeout):
            assert request.full_url == "http://127.0.0.1:8765/api/state"
            return io.BytesIO(b'{"now":"today","slot":{},"account":{}}' if kind == "running" else b'{}')

    monkeypatch.setattr(background, "build_opener", lambda *args: Opener())

    def connect(*args, **kwargs):
        if kind == "available":
            raise OSError("not listening")
        return io.BytesIO()

    monkeypatch.setattr(background.socket, "create_connection", connect)
    assert background.service_state(8765) == kind


def test_crash_recovery_reuses_existing_service_before_restarting(background, monkeypatch, tmp_path):
    monkeypatch.setattr(background.sys, "argv", ["background", "--root", str(tmp_path)])
    monkeypatch.setattr(background, "configure_logging", lambda root: None)
    states = iter(["available", "running", "available"])
    monkeypatch.setattr(background, "service_state", lambda port: next(states))
    starts, waits = [], []

    def serve(root, port):
        starts.append((root, port))
        if len(starts) == 1:
            raise RuntimeError("simulated crash")

    class Finished(Exception):
        pass

    def sleep(seconds):
        waits.append(seconds)
        if len(waits) == 3:
            raise Finished

    monkeypatch.setattr(background, "serve", serve)
    monkeypatch.setattr(background.time, "sleep", sleep)
    with pytest.raises(Finished):
        background.main()
    assert starts == [(tmp_path, 8765), (tmp_path, 8765)]
    assert waits == [30, 30, 30]
