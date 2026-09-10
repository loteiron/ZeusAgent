"""A failed import may roll back its own bytes, never a user's intervening edit."""

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import subprocess
import sys
from threading import Event
import time

import pytest


@pytest.mark.parametrize("existing", [False, True])
def test_failed_chat_import_preserves_edits_made_just_after_file_publication(tmp_path, monkeypatch, existing):
    from zeus_cli.hermes_import import import_hermes, scan_hermes_import
    from zeus_state import SessionDB

    source, target = tmp_path / "hermes", tmp_path / "zeus"
    source.mkdir()
    target.mkdir()
    monkeypatch.setenv("ZEUS_HOME", str(target))
    relative = Path("memories/MEMORY.md") if existing else Path("prompts/welcome.txt")
    (source / relative).parent.mkdir(parents=True, exist_ok=True)
    (source / relative).write_text("Imported text", encoding="utf-8")
    destination = target / relative
    if existing:
        destination.parent.mkdir(parents=True)
        destination.write_text("Existing notes", encoding="utf-8")
    with sqlite3.connect(source / "state.db") as conn:
        conn.execute("CREATE TABLE sessions(id TEXT PRIMARY KEY, source TEXT, title TEXT, started_at REAL)")
        conn.execute("INSERT INTO sessions VALUES ('old', 'cli', 'Old chat', 1)")
        # No messages table: merging the chat must fail after files were published.
    db = SessionDB(target / "state.db")
    db.close()
    preview = scan_hermes_import(str(source))
    publish = os.replace if existing else os.link
    injected = False

    def publish_then_edit(src, dst, *args, **kwargs):
        nonlocal injected
        result = publish(src, dst, *args, **kwargs)
        if not injected and Path(dst) == destination:
            injected = True
            destination.write_text("User's concurrent edit", encoding="utf-8")
        return result

    monkeypatch.setattr(os, "replace" if existing else "link", publish_then_edit)
    with pytest.raises(sqlite3.Error):
        import_hermes(source=str(source), scan_id=preview["scan_id"],
                      categories=["memories" if existing else "prompts", "chats"])
    assert injected, "The user edit must occur after a real publication"
    assert destination.is_file(), "Rollback erased a user's concurrent edit"
    assert destination.read_text(encoding="utf-8") == "User's concurrent edit"


@pytest.mark.parametrize("category", ["settings", "memories"])
def test_import_publication_serializes_with_existing_zeus_writers(tmp_path, monkeypatch, category):
    from zeus_cli.hermes_import import import_hermes, scan_hermes_import
    from zeus_cli.config import save_config

    source, target = tmp_path / "hermes", tmp_path / "zeus"
    source.mkdir()
    target.mkdir()
    monkeypatch.setenv("ZEUS_HOME", str(target))
    relative = Path("config.yaml") if category == "settings" else Path("memories/MEMORY.md")
    for home in (source, target):
        (home / relative).parent.mkdir(parents=True, exist_ok=True)
    (source / relative).write_text("display:\n  compact: true\n" if category == "settings" else "Imported notes")
    destination = target / relative
    destination.write_text("model: original\n" if category == "settings" else "Existing notes")
    preview = scan_hermes_import(str(source))
    publishing, writer_started, writer_finished = Event(), Event(), Event()
    replace = os.replace

    def pause_before_publication(src, dst, *args, **kwargs):
        if Path(dst) == destination and "staging" in Path(src).parts:
            publishing.set()
            assert writer_started.wait(5)
            # The established writer must wait until import publication releases
            # its lock; without coordination it wins here and is then overwritten.
            writer_finished.wait(0.5)
        return replace(src, dst, *args, **kwargs)

    def user_write():
        if category == "settings":
            writer_started.set()
            save_config({"model": "concurrent"}, strip_defaults=False)
        else:
            started_file = tmp_path / "memory-writer-started"
            script = ("from pathlib import Path\nimport sys\n"
                      "from tools.memory_tool_store import MemoryStore\n"
                      "Path(sys.argv[2]).touch()\n"
                      "with MemoryStore._file_lock(Path(sys.argv[1])):\n"
                      "    Path(sys.argv[1]).write_text('Concurrent notes')\n")
            with subprocess.Popen([sys.executable, "-c", script, str(destination), str(started_file)]) as child:
                deadline = time.monotonic() + 8
                while not started_file.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                assert started_file.exists()
                writer_started.set()
                assert child.wait(timeout=10) == 0
        writer_finished.set()

    monkeypatch.setattr(os, "replace", pause_before_publication)
    with ThreadPoolExecutor(max_workers=2) as pool:
        importing = pool.submit(import_hermes, source=str(source), scan_id=preview["scan_id"], categories=[category])
        assert publishing.wait(10)
        writer = pool.submit(user_write)
        importing.result(timeout=15)
        writer.result(timeout=15)
    assert ("model: concurrent" if category == "settings" else "Concurrent notes") in destination.read_text()
