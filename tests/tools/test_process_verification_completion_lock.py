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


def test_unread_child_completion_is_visible_while_evidence_is_being_persisted(tmp_path, monkeypatch):
    from tools import process_registry as module
    from tools import terminal_verification

    monkeypatch.setenv("ZEUS_HOME", str(tmp_path))
    registry = module.ProcessRegistry()
    session = module.ProcessSession(id="child-proof", command="pytest", owner_task_id="sa-child",
                                    notify_on_complete=True, output_buffer="UNREAD_RESULT\n")
    registry._running[session.id] = session
    entered, release = threading.Event(), threading.Event()

    def capture(session):
        entered.set()
        assert release.wait(5)

    monkeypatch.setattr(terminal_verification, "record_process_completion", capture)
    monkeypatch.setattr(module, "save_completed_result", lambda session: None)
    monkeypatch.setattr(registry, "_write_checkpoint", lambda: None)
    finisher = threading.Thread(target=registry._finish_exited, args=(session, 0))
    finisher.start()
    try:
        assert entered.wait(2)
        assert session.exited and session.id in registry._running
        assert registry.unread_completions_owned_by("sa-child") == [session]
        assert registry.unread_completions_owned_by("other-child") == []
        registry._completion_consumed.add(session.id)
        assert registry.unread_completions_owned_by("sa-child") == []
        registry._completion_consumed.clear()
    finally:
        release.set()
        finisher.join(3)
    assert registry.unread_completions_owned_by("sa-child") == [session]
