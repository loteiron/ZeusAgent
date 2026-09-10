"""The native observer must preserve actual psutil method binding."""

import os
from types import SimpleNamespace

import psutil

from tests.fakes import process_cleanup_trace


def test_status_observer_preserves_real_process_instance_binding(tmp_path, monkeypatch):
    process = psutil.Process(os.getpid())
    expected = process.status()
    # Activate the native diagnostic hook on every test host without changing
    # os.name globally or replacing psutil's actual process/status lookup.
    native_surface = SimpleNamespace(name="posix", getpgid=lambda pid: pid, killpg=lambda *_args: None)
    monkeypatch.setattr(process_cleanup_trace, "os", native_surface)
    trace = process_cleanup_trace.ProcessCleanupTrace(monkeypatch, tmp_path, 0, "method-binding")
    trace.owned.add(process.pid)

    assert process.status() == expected
    assert trace.events[-1]["event"] == "status"
    assert trace.events[-1]["pid"] == process.pid
    assert trace.events[-1]["status"] == expected
