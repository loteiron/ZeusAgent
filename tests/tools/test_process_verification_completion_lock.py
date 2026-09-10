"""Slow source identity capture must not monopolize the global process registry."""
import threading


def test_completion_stays_tracked_without_blocking_unrelated_registry_queries(tmp_path, monkeypatch):
    from tools import process_registry as module
    from tools import terminal_verification

    monkeypatch.setenv("ZEUS_HOME", str(tmp_path))
    registry = module.ProcessRegistry()
    session = module.ProcessSession(id="proof", command="pytest", exited=True, exit_code=0)
    registry._running[session.id] = session
    entered, release, acquired = threading.Event(), threading.Event(), threading.Event()
    calls = []

    def capture(session):
        calls.append(session.id)
        entered.set()
        assert release.wait(5)

    monkeypatch.setattr(terminal_verification, "record_process_completion", capture)
    monkeypatch.setattr(module, "save_completed_result", lambda session: None)
    monkeypatch.setattr(registry, "_write_checkpoint", lambda: None)
    first = threading.Thread(target=registry._move_to_finished, args=(session,))
    second = threading.Thread(target=registry._move_to_finished, args=(session,))

    def query():
        with registry._lock:
            assert session.id in registry._running
            acquired.set()

    first.start()
    try:
        assert entered.wait(2)
        second.start()
        reader = threading.Thread(target=query)
        reader.start()
        assert acquired.wait(1), "source hashing blocked the entire registry"
        reader.join(1)
    finally:
        release.set()
        first.join(3)
        second.join(3)
    assert calls == ["proof"]
    assert session.id not in registry._running
    assert session.id in registry._finished
