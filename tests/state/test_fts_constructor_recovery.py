"""Real corrupt FTS structure recovery keeps canonical data and rollback guarantees."""
import sqlite3
from contextlib import contextmanager

import pytest

from zeus_state import SessionDB
from zeus_state_common import FTS_STALE_KEY, _FTS_TRIGGERS


@pytest.fixture
def corrupt(tmp_path, monkeypatch):
    path = tmp_path / "state.db"
    db = SessionDB(path)
    if not db._fts_enabled:
        db.close()
        pytest.skip("FTS5 unavailable")
    db.create_session("owned", "cli")
    db.append_message("owned", "user", "canonical telescope survives")
    db._conn.execute("CREATE TABLE messages_fts_data_backup(value TEXT)")
    db._conn.execute("INSERT INTO messages_fts_data_backup VALUES ('unrelated keepsake')")
    db._conn.commit()
    db.close()
    with sqlite3.connect(path) as conn:
        for trigger in _FTS_TRIGGERS:
            conn.execute(f"DROP TRIGGER IF EXISTS {trigger}")
        conn.execute("UPDATE messages_fts_data SET block=X'DEADBEEFDEADBEEFDEADBEEFDEADBEEF'")
        conn.execute("INSERT OR REPLACE INTO state_meta VALUES (?, '1')", (FTS_STALE_KEY,))
    monkeypatch.setattr(SessionDB, "_foreign_state_db_holders", lambda self: [(999999, str(path))])
    db = SessionDB(path)
    monkeypatch.setattr(db, "_foreign_state_db_holders", lambda: [])
    assert db._fts_stale
    yield db
    db.close()


def _canonical(db):
    return [tuple(row) for row in db._conn.execute("SELECT id, session_id, role, content FROM messages ORDER BY id")]


def _schema(db):
    return [tuple(row) for row in db._conn.execute("SELECT name, rootpage, sql FROM sqlite_master WHERE type='table' ORDER BY name")]


def test_constructor_recovery_preserves_canonical_rows_and_similarly_prefixed_table(corrupt):
    db = corrupt
    original = _canonical(db)
    assert db._recover_stale_fts(db._conn.cursor(), legacy=False, timeout_seconds=0)
    assert _canonical(db) == original
    assert db._conn.execute("SELECT value FROM messages_fts_data_backup").fetchone()[0] == "unrelated keepsake"
    assert db._conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert not db._conn.execute("PRAGMA foreign_key_check").fetchall()
    assert db._conn.execute("PRAGMA writable_schema").fetchone()[0] == 0
    db._conn.execute("INSERT INTO messages_fts(messages_fts, rank) VALUES('integrity-check', 1)")
    assert db.search_messages("telescope")
    db.append_message("owned", "assistant", "restored index sync")
    assert db.search_messages("restored index")


@pytest.mark.parametrize("failure", ["schema_delete", "create_vtable"])
def test_fallback_failure_rolls_back_detachment_and_resets_writable_schema(corrupt, failure):
    db = corrupt
    before_schema, before_rows = _schema(db), _canonical(db)
    writable, injected = False, False

    def trace(statement):
        nonlocal writable
        if "writable_schema=ON" in statement:
            writable = True

    def authorize(action, first, second, database, trigger):
        nonlocal injected
        matches = ((failure == "schema_delete" and writable and action == sqlite3.SQLITE_DELETE and first == "sqlite_master") or
                   (failure == "create_vtable" and action == sqlite3.SQLITE_CREATE_VTABLE and first == "messages_fts"))
        if matches and not injected:
            injected = True
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    db._conn.set_trace_callback(trace)
    db._conn.set_authorizer(authorize)
    try:
        assert not db._recover_stale_fts(db._conn.cursor(), legacy=False, timeout_seconds=0)
    finally:
        db._conn.set_authorizer(None)
        db._conn.set_trace_callback(None)
    assert injected, "failure must reach the actual schema fallback"
    assert _schema(db) == before_schema
    assert _canonical(db) == before_rows
    assert not db._conn.in_transaction
    assert db._conn.execute("PRAGMA writable_schema").fetchone()[0] == 0
    assert db._conn.execute("SELECT value FROM state_meta WHERE key=?", (FTS_STALE_KEY,)).fetchone()[0] == "1"
    db.append_message("owned", "assistant", "write after failed repair")
    assert db.search_messages("failed repair")


@pytest.mark.parametrize("guard", ["holder", "admission"])
def test_constructor_fallback_cannot_bypass_rebuild_ownership(corrupt, monkeypatch, guard):
    db = corrupt
    before = _schema(db)
    monkeypatch.setattr(db, "_recover_stale_fts_locked", lambda *args, **kwargs: pytest.fail("rebuild authority was bypassed"))
    if guard == "holder":
        monkeypatch.setattr(db, "_foreign_state_db_holders", lambda: [(999998, str(db.db_path))])
    else:
        @contextmanager
        def denied(*args, **kwargs):
            yield False
        monkeypatch.setattr("zeus_state_schema.fts_rebuild_admission", denied)
    assert not db._recover_stale_fts(db._conn.cursor(), legacy=False, timeout_seconds=0)
    assert _schema(db) == before
    assert db._conn.execute("PRAGMA writable_schema").fetchone()[0] == 0


def test_interrupted_schema_detachment_rolls_back_before_propagating(corrupt):
    db = corrupt
    before_schema, before_rows = _schema(db), _canonical(db)
    cursor = db._conn.cursor()

    class InterruptedCursor:
        def __getattr__(self, name):
            return getattr(cursor, name)

        def executescript(self, sql):
            if "PRAGMA writable_schema=ON" in sql:
                # Execute actual schema deletion in an open SQLite transaction,
                # then model cancellation before the cache reset and rebuild.
                prefix = sql.split("PRAGMA writable_schema=RESET;", 1)[0]
                cursor.executescript(prefix)
                raise KeyboardInterrupt("cancelled during FTS detachment")
            return cursor.executescript(sql)

    with pytest.raises(KeyboardInterrupt, match="FTS detachment"):
        db._recover_stale_fts(InterruptedCursor(), legacy=False, timeout_seconds=0)
    assert not db._conn.in_transaction, "cancellation left destructive schema edits uncommitted"
    assert db._conn.execute("PRAGMA writable_schema").fetchone()[0] == 0
    assert _schema(db) == before_schema
    assert _canonical(db) == before_rows
