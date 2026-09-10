"""Failed metadata cleanup cannot orphan a child or erase another owner's record."""

import json
from pathlib import Path
from types import SimpleNamespace

from zeus_cli.local_runtime import supervisor as runtime


def test_unlink_failure_still_stops_child_and_closes_log(tmp_path, monkeypatch):
    monkeypatch.setenv("ZEUS_HOME", str(tmp_path))
    sup = runtime.LlamaServerSupervisor(tmp_path / "install", tmp_path / "models", port=18435)
    stopped = []
    sup.proc = SimpleNamespace(pid=12345, poll=lambda: 0 if stopped else None)
    sup._write_state()
    sup._log_handle = (tmp_path / "server.log").open("w")
    handle = sup._log_handle
    monkeypatch.setattr(sup, "_terminate_tree", lambda proc: stopped.append(proc.pid))
    unlink = Path.unlink

    def fail_state_unlink(path, *args, **kwargs):
        if path == runtime.state_path():
            raise PermissionError("injected metadata cleanup failure")
        return unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_state_unlink)
    try:
        sup.stop()
        assert stopped == [12345]
        assert handle.closed and sup._log_handle is None
    finally:
        handle.close()


def test_stop_preserves_replacement_owner_state(tmp_path, monkeypatch):
    monkeypatch.setenv("ZEUS_HOME", str(tmp_path))
    sup = runtime.LlamaServerSupervisor(tmp_path / "install", tmp_path / "models", port=18435)
    sup.proc = SimpleNamespace(pid=12345, poll=lambda: 0)
    sup._write_state()
    replacement = json.dumps({"pid": 54321, "process_start_time": 99,
                              "base_url": sup.base_url, "api_key": sup.api_key})
    runtime.state_path().write_text(replacement)
    sup.stop()
    sup.stop()
    assert runtime.state_path().read_text() == replacement
