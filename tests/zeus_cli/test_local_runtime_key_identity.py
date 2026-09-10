"""Concurrent initialization and read failures cannot silently rotate a local key."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading

import pytest

from zeus_cli.local_runtime import supervisor as runtime


def test_concurrent_initializers_share_one_persisted_key(tmp_path, monkeypatch):
    monkeypatch.setenv("ZEUS_HOME", str(tmp_path))
    first_entered, second_generated = threading.Event(), threading.Event()
    issued, counter_lock = [], threading.Lock()

    def generate(size):
        with counter_lock:
            value = f"local-test-key-{len(issued):020d}"
            issued.append(value)
            first = len(issued) == 1
        if first:
            first_entered.set()
            # Without serialization the second initializer generates a different
            # key while the first is paused. With a lock it waits for this write.
            second_generated.wait(3)
        else:
            second_generated.set()
        return value

    monkeypatch.setattr(runtime.secrets, "token_urlsafe", generate)
    with ThreadPoolExecutor(max_workers=2) as workers:
        first = workers.submit(runtime._stable_api_key)
        assert first_entered.wait(3)
        second = workers.submit(runtime._stable_api_key)
        values = [first.result(timeout=8), second.result(timeout=8)]
    assert values[0] == values[1]
    assert len(issued) == 1
    assert (runtime.runtimes_root() / ".api_key").read_text() == values[0]


def test_unreadable_existing_key_is_not_overwritten(tmp_path, monkeypatch):
    monkeypatch.setenv("ZEUS_HOME", str(tmp_path))
    path = runtime.runtimes_root() / ".api_key"
    path.parent.mkdir(parents=True)
    original = b"local-test-existing-key-123456789"
    path.write_bytes(original)
    read_text = Path.read_text

    def denied(candidate, *args, **kwargs):
        if candidate == path:
            raise PermissionError("injected key read failure")
        return read_text(candidate, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", denied)
    with pytest.raises(PermissionError, match="injected key read failure"):
        runtime._stable_api_key()
    assert path.read_bytes() == original
