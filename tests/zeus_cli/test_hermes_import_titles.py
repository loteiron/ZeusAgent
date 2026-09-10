"""Real SQLite imports preserve titles across different Hermes home directories."""
import hashlib
import sqlite3

from zeus_cli.hermes_import import import_hermes, scan_hermes_import
from zeus_cli.hermes_import_sessions import merge_chats
from zeus_state import SessionDB


def _source(home, content):
    home.mkdir()
    (home / "config.yaml").write_text("model: fixture\n", encoding="utf-8")
    with sqlite3.connect(home / "state.db") as conn:
        conn.executescript("CREATE TABLE sessions(id TEXT PRIMARY KEY, source TEXT, title TEXT, started_at REAL);"
                           "CREATE TABLE messages(id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT, timestamp REAL);")
        conn.execute("INSERT INTO sessions VALUES ('packaged-hermes-fixture', 'cli', 'Imported package acceptance', 100)")
        conn.execute("INSERT INTO messages VALUES (1, 'packaged-hermes-fixture', 'user', ?, 100)", (content,))
    return home


def _snapshot(home):
    return {str(file.relative_to(home)): hashlib.sha256(file.read_bytes()).hexdigest()
            for file in home.rglob("*") if file.is_file()}


def _import(source):
    preview = scan_hermes_import(str(source))
    return import_hermes(source=str(source), scan_id=preview["scan_id"], categories=["chats"])


def test_same_original_id_and_title_from_two_sources_import_and_repeat_without_renaming(tmp_path, monkeypatch):
    first = _source(tmp_path / "Hermes source çığ one", "first source message")
    second = _source(tmp_path / "Hermes source çığ two", "second source message")
    target = tmp_path / "Zeus"
    target.mkdir()
    monkeypatch.setenv("ZEUS_HOME", str(target))
    before = [_snapshot(first), _snapshot(second)]
    db = SessionDB(target / "state.db")
    db.create_session("existing-user-session", "cli")
    db.set_session_title("existing-user-session", "Imported package acceptance")
    db.append_message("existing-user-session", "user", "preserve my conversation")
    db.close()

    assert _import(first)["imported"]["chats"] == 1
    assert _import(second)["imported"]["chats"] == 1
    with sqlite3.connect(target / "state.db") as conn:
        imported = conn.execute("SELECT id, title FROM sessions WHERE end_reason='hermes_import' ORDER BY id").fetchall()
        assert len(imported) == 2
        assert len({title for _, title in imported}) == 2
        assert all(title.startswith("Imported package acceptance") for _, title in imported)
        assert conn.execute("SELECT content FROM messages ORDER BY id").fetchall() == [
            ("preserve my conversation",), ("first source message",), ("second source message",),
        ]
    # Imported transcripts become user history: a later rename must survive a rescan.
    db = SessionDB(target / "state.db")
    db.set_session_title(imported[0][0], "My chosen imported title")
    db.close()
    assert _import(first)["imported"]["chats"] == 0
    assert _import(second)["imported"]["chats"] == 0
    with sqlite3.connect(target / "state.db") as conn:
        assert conn.execute("SELECT title FROM sessions WHERE id='existing-user-session'").fetchone() == ("Imported package acceptance",)
        assert conn.execute("SELECT title FROM sessions WHERE id=?", (imported[0][0],)).fetchone() == ("My chosen imported title",)
        assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone() == (3,)
        assert conn.execute("SELECT COUNT(*) FROM messages").fetchone() == (3,)
    assert [_snapshot(first), _snapshot(second)] == before


def test_user_can_already_own_the_generated_import_title_without_being_renamed(tmp_path):
    source = _source(tmp_path / "source", "imported message") / "state.db"
    before = source.read_bytes()
    # Observe the real generated title in an empty DB rather than reproducing its algorithm.
    pilot = tmp_path / "pilot.db"
    assert merge_chats(source, pilot, "same-source-identity") == (1, 0)
    with sqlite3.connect(pilot) as conn:
        candidate = conn.execute("SELECT title FROM sessions").fetchone()[0]
    target = tmp_path / "target.db"
    db = SessionDB(target)
    db.create_session("user-owned", "cli")
    db.set_session_title("user-owned", candidate)
    db.append_message("user-owned", "user", "existing message")
    db.close()
    assert merge_chats(source, target, "same-source-identity") == (1, 0)
    with sqlite3.connect(target) as conn:
        rows = conn.execute("SELECT id, title FROM sessions ORDER BY id").fetchall()
        imported = next(row for row in rows if row[0] != "user-owned")
        assert len({row[1] for row in rows}) == 2
        assert dict(rows)["user-owned"] == candidate
        assert len(imported[1]) <= SessionDB.MAX_TITLE_LENGTH
    assert merge_chats(source, target, "same-source-identity") == (0, 1)
    with sqlite3.connect(target) as conn:
        assert conn.execute("SELECT id, title FROM sessions ORDER BY id").fetchall() == rows
        assert conn.execute("SELECT content FROM messages ORDER BY id").fetchall() == [("existing message",), ("imported message",)]
    assert source.read_bytes() == before
