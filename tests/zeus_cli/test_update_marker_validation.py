"""A corrupt update marker must recover without stranding the next update."""

import os

import pytest

from zeus_cli import update_lock


@pytest.mark.parametrize("started_at", [b"nan", b"inf", b"-inf", b"1e999", b"\xff"])
def test_invalid_timestamp_recovers_and_next_live_holder_is_respected(
    tmp_path, monkeypatch, started_at
):
    marker = tmp_path / update_lock.MARKER_NAME
    marker.write_bytes(str(os.getpid()).encode() + b"\n" + started_at + b"\n")
    # Keep the parser contract independent of the host's process visibility.
    monkeypatch.setattr(update_lock, "_pid_alive", lambda pid: pid == os.getpid())
    monkeypatch.setattr(update_lock, "_is_ancestor_pid", lambda pid: False)
    monkeypatch.delenv(update_lock.HANDOFF_PID_ENV, raising=False)

    assert update_lock.read_live_update(path=marker) is None
    assert not marker.exists()
    first = update_lock.UpdateLock(path=marker)
    second = update_lock.UpdateLock(path=marker)
    try:
        assert first.acquire() is True
        assert second.acquire() is False
        assert str(os.getpid()) in update_lock.describe_holder(second.holder)
        second.release()
        assert marker.exists()
    finally:
        first.release()
    assert not marker.exists()
