"""Read-only SQLite snapshots and additive, namespaced Hermes transcript imports."""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
from pathlib import Path
import sqlite3
import shutil
import tempfile
import time


@contextmanager
def readonly_database(path: Path):
    conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA query_only=ON")
        yield conn
    finally:
        conn.close()


def backup_database(source: Path, destination: Path) -> None:
    """Snapshot copies, never open the source in SQLite (WAL readers can create -shm)."""
    from zeus_cli.hermes_import_files import digest, is_link

    def version():
        files = [source, Path(str(source) + "-wal")]
        if any(is_link(path) for path in files):
            raise ValueError("Linked databases cannot be imported.")
        return {path.name: digest(path) for path in files if path.is_file()}

    destination.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()

    def progress(status, remaining, total):
        if time.monotonic() - started > 60:
            raise ValueError("The database is busy; close Hermes and scan again.")

    before = version()
    with tempfile.TemporaryDirectory(prefix="zeus-hermes-snapshot-") as directory:
        copied = Path(directory) / source.name
        for name in before:
            shutil.copyfile(source.parent / name, copied.parent / name)
        if before != version():
            raise ValueError("Hermes conversations changed while copying; close Hermes and scan again.")
        # Recovery and WAL shared-memory coordination happen only on private copies.
        src = sqlite3.connect(copied)
        dest = sqlite3.connect(destination)
        try:
            src.backup(dest, pages=256, progress=progress)
        finally:
            dest.close()
            src.close()


def chat_count(source: Path) -> int:
    if not source.is_file():
        return 0
    try:
        with tempfile.TemporaryDirectory(prefix="zeus-hermes-count-") as directory:
            copied = Path(directory) / "state.db"
            backup_database(source, copied)
            with readonly_database(copied) as conn:
                return int(conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0])
    except sqlite3.Error as exc:
        raise ValueError("The source conversation database is not compatible or is busy.") from exc


def _columns(conn, table):
    return {row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')}


def _insert(conn, table, values):
    keys = list(values)
    conn.execute(f'INSERT INTO "{table}" (' + ",".join('"' + key + '"' for key in keys) + ") VALUES (" +
                 ",".join("?" for _ in keys) + ")", [values[key] for key in keys])


def _available_import_title(conn, original, sid, db):
    """Allocate inside the import transaction; never rename an existing title owner.

    The complete namespaced ID distinguishes equal source session IDs from two
    homes. A user can still own any generated name, so consult the same write
    connection (the general lineage helper's read pool cannot see pending rows).
    """
    limit = db.MAX_TITLE_LENGTH
    base = db.sanitize_title(str(original or "Hermes conversation")[:limit]) or "Hermes conversation"
    identity = hashlib.sha256(sid.encode("utf-8")).hexdigest()[:12]
    sequence = 1
    while True:
        suffix = " · Hermes " + identity + (f" #{sequence}" if sequence > 1 else "")
        candidate = base[:limit - len(suffix)] + suffix
        if not conn.execute("SELECT 1 FROM sessions WHERE title=?", (candidate,)).fetchone():
            return candidate
        sequence += 1


def merge_chats(snapshot: Path, target: Path, source_key: str, *, profile="default") -> tuple[int, int]:
    """Import complete conversations in one live-database transaction. Existing IDs never change."""
    from zeus_state import SessionDB

    db = SessionDB(target)
    try:
        with readonly_database(snapshot) as source:
            sessions = source.execute("SELECT * FROM sessions ORDER BY started_at, id").fetchall()
            if len(sessions) > 100_000:
                raise ValueError("This import exceeds 100,000 conversations; select a smaller Hermes profile.")
            names = {str(row["id"]): "hermes:" + source_key + ":" + hashlib.sha256(
                     str(row["id"]).encode("utf-8")).hexdigest()[:24] for row in sessions}

            def write(conn):
                imported, skipped = 0, 0
                session_cols, message_cols = _columns(conn, "sessions"), _columns(conn, "messages")
                created = []
                for row in sessions:
                    sid, original = names[str(row["id"])], dict(row)
                    if conn.execute("SELECT 1 FROM sessions WHERE id=?", (sid,)).fetchone():
                        skipped += 1
                        continue
                    values = {key: value for key, value in original.items() if key in session_cols}
                    # Imported transcripts are local history, not live routing or running agents.
                    values.update(id=sid, source="cli", session_key=None, chat_id=None, thread_id=None,
                                  origin_json=None, user_id=None, parent_session_id=None, system_prompt_hash=None,
                                  profile_name=profile, handoff_state=None, handoff_platform=None, handoff_error=None,
                                  ended_at=original.get("ended_at") or time.time(), end_reason="hermes_import")
                    values["title"] = _available_import_title(conn, original.get("title"), sid, db)
                    prompt = original.get("system_prompt")
                    if not prompt and original.get("system_prompt_hash"):
                        try:
                            prompt_row = source.execute("SELECT prompt FROM system_prompts WHERE hash=?",
                                                        (original["system_prompt_hash"],)).fetchone()
                            prompt = prompt_row[0] if prompt_row else None
                        except sqlite3.Error:
                            prompt = None
                    values["system_prompt"] = prompt
                    values["message_count"] = 0
                    values.setdefault("started_at", time.time())
                    _insert(conn, "sessions", values)
                    created.append((sid, original))
                    imported += 1
                for sid, original in created:
                    parent = names.get(str(original.get("parent_session_id")))
                    if parent and parent != sid:
                        conn.execute("UPDATE sessions SET parent_session_id=? WHERE id=?", (parent, sid))
                    count = 0
                    for row in source.execute("SELECT * FROM messages WHERE session_id=? ORDER BY id", (original["id"],)):
                        values = {key: row[key] for key in row.keys() if key in message_cols and key != "id"}
                        values["session_id"] = sid
                        values.setdefault("timestamp", original.get("started_at") or time.time())
                        # Do not replay imported tool effects or platform delivery identifiers.
                        values.update(effect_disposition="historical", platform_message_id=None)
                        _insert(conn, "messages", values)
                        count += 1
                    conn.execute("UPDATE sessions SET message_count=? WHERE id=?", (count, sid))
                return imported, skipped

            return db._execute_write(write, patience_s=30)
    finally:
        db.close()
