"""Restart adopted servers through real state decoding and verified process identity."""

import json
import signal

import pytest

from zeus_cli.local_runtime import bootstrap as boot, endpoint, supervisor


@pytest.mark.parametrize("operation", ["refresh", "stale-presets"])
def test_adopted_restart_preserves_pid_and_stops_before_replacement(tmp_path, monkeypatch, operation):
    monkeypatch.setenv("ZEUS_HOME", str(tmp_path))
    monkeypatch.setattr(boot, "_SUPERVISOR", None)
    config = {"local_runtime": {"enabled": True, "backend": "cpu", "tag": "test-tag"}}
    path = supervisor.state_path()
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"pid": 12345, "process_start_time": 73,
                               "base_url": "http://127.0.0.1:18435/v1", "api_key": "test-key"}))
    events = []

    def kill(pid, sig):
        assert (pid, sig) == (12345, signal.SIGTERM)
        events.append("stop")

    class Replacement:
        base_url = "http://127.0.0.1:18435/v1"

        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            events.append("start")

    monkeypatch.setattr(endpoint, "_pid_alive", lambda pid: pid == 12345 and "stop" not in events)
    monkeypatch.setattr("gateway.status._get_process_start_time", lambda pid: 73)
    monkeypatch.setattr(boot.os, "kill", kill)
    monkeypatch.setattr(boot, "_presets_stale", lambda: True)
    monkeypatch.setattr(boot, "staged_models", lambda: [tmp_path / "model.gguf"])
    monkeypatch.setattr(boot, "_generate_presets", lambda *args: None)
    monkeypatch.setattr(boot, "_start_idle_sweeper", lambda sup: None)
    monkeypatch.setattr("zeus_cli.config.load_config", lambda: config)
    monkeypatch.setattr("zeus_cli.local_runtime.binaries.installed_tags", lambda: ["test-tag"])
    monkeypatch.setattr("zeus_cli.local_runtime.binaries.ensure_runtime_installed", lambda *args: tmp_path)
    monkeypatch.setattr(supervisor, "LlamaServerSupervisor", Replacement)

    result = boot.refresh_local_runtime() if operation == "refresh" else boot.ensure_local_runtime(config)
    assert result
    assert events == ["stop", "start"]


@pytest.mark.parametrize("recorded_start", [None, 0, True, "73", 72])
def test_adopted_stop_refuses_missing_or_reused_process_identity(monkeypatch, recorded_start):
    calls = []
    monkeypatch.setattr("gateway.status._get_process_start_time", lambda pid: 73)
    monkeypatch.setattr(endpoint, "_pid_alive", lambda pid: False)
    monkeypatch.setattr(boot.os, "kill", lambda *args: calls.append(args))
    state = {"pid": 12345, "process_start_time": recorded_start}
    assert boot._stop_state_server(state) is False
    assert calls == []
