"""Stop must win over both a pending restart and an in-flight spawn."""

import logging
import threading
from types import SimpleNamespace

from zeus_cli.local_runtime import supervisor as runtime


def test_stop_during_backoff_never_respawns(tmp_path, monkeypatch):
    monkeypatch.setenv("ZEUS_HOME", str(tmp_path))
    sup = runtime.LlamaServerSupervisor(tmp_path / "install", tmp_path / "models", port=18435)
    sup.proc = SimpleNamespace(pid=12345, poll=lambda: 1)
    sup._write_state()
    backoff, spawned = threading.Event(), []

    class BackoffNotice(logging.Handler):
        def emit(self, record):
            if "restart #" in record.getMessage():
                backoff.set()

    def spawn():
        spawned.append(True)
        sup._stopping = True

    handler = BackoffNotice()
    runtime.logger.addHandler(handler)
    monkeypatch.setattr(sup, "_spawn", spawn)
    monkeypatch.setattr(sup, "_reap_orphaned_children", lambda: None)
    monkeypatch.setattr(sup, "_wait_health", lambda timeout: None)
    worker = threading.Thread(target=sup._watch, daemon=True)
    worker.start()
    try:
        assert backoff.wait(3), "watchdog did not enter restart backoff"
        sup.stop()
        worker.join(timeout=3)
        assert not worker.is_alive()
        assert spawned == []
        assert not runtime.state_path().exists()
    finally:
        sup.stop()
        runtime.logger.removeHandler(handler)
        worker.join(timeout=3)


def test_stop_during_spawn_removes_state_and_closes_log(tmp_path, monkeypatch):
    monkeypatch.setenv("ZEUS_HOME", str(tmp_path))
    sup = runtime.LlamaServerSupervisor(tmp_path / "install", tmp_path / "models", port=18435)
    monkeypatch.setattr(runtime, "server_binary", lambda install: install / "llama-server")
    entered, release, stopped = threading.Event(), threading.Event(), threading.Event()
    errors = []

    def popen(*args, **kwargs):
        entered.set()
        assert release.wait(3), "test did not release spawn"
        return SimpleNamespace(pid=12345, poll=lambda: 1)

    def spawn():
        try:
            sup._spawn()
        except Exception as exc:
            errors.append(exc)

    def stop():
        try:
            sup.stop()
        except Exception as exc:
            errors.append(exc)
        finally:
            stopped.set()

    monkeypatch.setattr(runtime.subprocess, "Popen", popen)
    starter = threading.Thread(target=spawn, daemon=True)
    stopper = threading.Thread(target=stop, daemon=True)
    starter.start()
    try:
        assert entered.wait(3)
        stopper.start()
        # The old stop returns while Popen is still in flight; serialized stop
        # waits for that spawn. Release it in either case without timing assertions.
        stopped.wait(2)
    finally:
        release.set()
        starter.join(timeout=3)
        if stopper.ident is not None:
            stopper.join(timeout=3)
    assert not starter.is_alive() and not stopper.is_alive()
    assert errors == []
    assert not runtime.state_path().exists()
    assert sup._log_handle is None
