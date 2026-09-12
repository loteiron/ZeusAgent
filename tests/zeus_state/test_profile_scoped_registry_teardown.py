"""Deleting one live profile closes only its own handles and waits for its pending close."""
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from pathlib import Path
import threading

import pytest

import zeus_state_registry as registry


def test_scoped_close_respects_directory_boundaries_and_filesystem_roots(tmp_path):
    selected = tmp_path / "alpha" / "state.db"
    sibling = tmp_path / "alpha-other" / "state.db"
    assert registry._path_is_under(selected, selected.parent)
    assert registry._path_is_under(selected, Path(selected.anchor))
    assert not registry._path_is_under(sibling, selected.parent)


def test_scoped_close_waits_for_its_admitted_teardown_only(tmp_path, monkeypatch):
    home = tmp_path / "removed"
    home.mkdir()
    other_home = tmp_path / "kept"
    other_home.mkdir()
    db = registry.acquire(home / "state.db")
    other = registry.acquire(other_home / "state.db")
    entered = threading.Event()
    proceed = threading.Event()
    original = registry._teardown

    def pause_selected(candidate):
        if candidate is db:
            entered.set()
            if not proceed.wait(5):
                raise RuntimeError("Test teardown was not released")
        original(candidate)

    monkeypatch.setattr(registry, "_teardown", pause_selected)
    with ThreadPoolExecutor(max_workers=3) as pool:
        releasing = pool.submit(registry.release, db)
        try:
            assert entered.wait(5)
            # Its final release has already removed the generation from the map.
            closing = pool.submit(registry.close_all_under, home)
            with pytest.raises(TimeoutError):
                closing.result(timeout=0.1)
            # Another directory must not wait for the removed profile's barrier.
            unrelated = pool.submit(registry.close_all_under, other_home)
            assert unrelated.result(timeout=2) == 1
            proceed.set()
            assert releasing.result(timeout=5) is True
            assert closing.result(timeout=5) == 0
            assert registry.close_all_under(home) == 0
        finally:
            proceed.set()
            releasing.result(timeout=5)
            registry.release_or_close(db)
            registry.release_or_close(other)
