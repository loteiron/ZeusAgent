"""Hermes import preserves source bytes and existing Zeus data, including collisions."""

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest
import yaml


@pytest.fixture
def homes(tmp_path, monkeypatch):
    source, target = tmp_path / "hermes", tmp_path / "zeus"
    source.mkdir()
    target.mkdir()
    monkeypatch.setenv("ZEUS_HOME", str(target))
    (source / "config.yaml").write_text("model: imported-model\ndisplay:\n  compact: true\n", encoding="utf-8")
    return source, target


def seed_chat(home, *, sid="chat1", content="hello"):
    with sqlite3.connect(home / "state.db") as conn:
        conn.executescript("CREATE TABLE sessions(id TEXT PRIMARY KEY, source TEXT, title TEXT, started_at REAL);"
                           "CREATE TABLE messages(id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT, timestamp REAL);")
        conn.execute("INSERT INTO sessions VALUES (?, 'cli', 'Imported chat', 100)", (sid,))
        conn.execute("INSERT INTO messages VALUES (1, ?, 'user', ?, 100)", (sid, content))


def snapshot(root):
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob("*") if path.is_file() and not path.name.endswith(("-shm", "-wal"))}


def scan(source):
    from zeus_cli.hermes_import import scan_hermes_import
    return scan_hermes_import(str(source))


def apply(source, preview, categories):
    from zeus_cli.hermes_import import import_hermes
    return import_hermes(source=str(source), scan_id=preview["scan_id"], categories=categories)


def test_preview_reads_no_secret_values_and_does_not_change_source(homes):
    source, target = homes
    secret = "ghp_" + "x" * 36
    (source / ".env").write_text("TOKEN=" + secret, encoding="utf-8")
    (source / "config.yaml").write_text("model: a\napi_key: " + secret + "\n", encoding="utf-8")
    before = snapshot(source)
    preview = scan(source)
    assert snapshot(source) == before
    assert secret not in json.dumps(preview)
    assert "config.yaml" not in snapshot(target)
    assert preview["scan_id"]


def test_settings_fill_missing_keys_and_preserve_existing_values(homes):
    source, target = homes
    (target / "config.yaml").write_text("model: own-model\ndisplay:\n  skin: zeus\n", encoding="utf-8")
    preview = scan(source)
    result = apply(source, preview, ["settings"])
    config = yaml.safe_load((target / "config.yaml").read_text())
    assert config["model"] == "own-model"
    assert config["display"] == {"skin": "zeus", "compact": True}
    assert result["backup_path"]
    assert (Path(result["backup_path"]) / "config.yaml").is_file()


def test_credentials_and_service_autostart_settings_are_not_imported(homes):
    source, target = homes
    (source / "config.yaml").write_text("model: a\napi_key: secret\ngateway:\n  enabled: true\nproviders:\n  demo:\n    api_key: secret\n    base_url: https://example.invalid\n", encoding="utf-8")
    apply(source, scan(source), ["settings"])
    config = yaml.safe_load((target / "config.yaml").read_text())
    assert "api_key" not in config
    assert "gateway" not in config
    assert "api_key" not in config["providers"]["demo"]


def test_chats_are_visible_and_idempotent_without_replacing_existing_chat(homes):
    source, target = homes
    seed_chat(source)
    from zeus_state import SessionDB
    db = SessionDB(target / "state.db")
    db.create_session("chat1", "cli")
    db.append_message("chat1", "user", "keep me")
    db.close()
    original = snapshot(source)
    first = apply(source, scan(source), ["chats"])
    assert first["imported"]["chats"] == 1
    second = apply(source, scan(source), ["chats"])
    assert second["imported"]["chats"] == 0
    with sqlite3.connect(target / "state.db") as conn:
        rows = conn.execute("SELECT session_id, content FROM messages ORDER BY id").fetchall()
    assert rows[0] == ("chat1", "keep me")
    assert len(rows) == 2
    assert rows[1][0] != "chat1" and rows[1][1] == "hello"
    assert snapshot(source) == original


def test_memory_and_skill_name_conflicts_are_preserved_under_import_namespace(homes):
    source, target = homes
    for home, content in ((source, "imported"), (target, "existing")):
        (home / "memories").mkdir()
        (home / "memories" / "MEMORY.md").write_text(content, encoding="utf-8")
        (home / "skills" / "demo").mkdir(parents=True)
        (home / "skills" / "demo" / "SKILL.md").write_text(content, encoding="utf-8")
    result = apply(source, scan(source), ["memories", "skills"])
    memory = (target / "memories" / "MEMORY.md").read_text()
    assert memory.startswith("existing") and "imported" in memory
    assert (target / "skills" / "demo" / "SKILL.md").read_text() == "existing"
    imported = [p for p in target.rglob("SKILL.md") if "hermes" in str(p.relative_to(target))]
    assert any(p.read_text() == "imported" for p in imported)
    assert result["conflicts"] >= 2


def test_stale_preview_refuses_before_any_target_changes(homes):
    source, target = homes
    preview = scan(source)
    (source / "config.yaml").write_text("model: changed\n", encoding="utf-8")
    before = snapshot(target)
    with pytest.raises(ValueError, match="changed|again"):
        apply(source, preview, ["settings"])
    assert snapshot(target) == before


def test_source_target_overlap_is_rejected(homes):
    _, target = homes
    (target / "config.yaml").write_text("model: a", encoding="utf-8")
    with pytest.raises(ValueError):
        scan(target)


def test_unknown_category_or_scan_id_cannot_import(homes):
    source, _ = homes
    preview = scan(source)
    with pytest.raises(ValueError):
        apply(source, preview, ["credentials"])
    with pytest.raises(ValueError):
        apply(source, {"scan_id": "../../other"}, ["settings"])


def test_existing_malformed_target_settings_are_never_replaced(homes):
    source, target = homes
    original = "[broken yaml"
    (target / "config.yaml").write_text(original, encoding="utf-8")
    preview = scan(source)
    with pytest.raises(ValueError):
        apply(source, preview, ["settings"])
    assert (target / "config.yaml").read_text() == original


def test_named_profiles_import_to_distinct_profile_and_never_overwrite(homes):
    source, target = homes
    profile = source / "profiles" / "work"
    profile.mkdir(parents=True)
    (profile / "config.yaml").write_text("model: profile-model\n", encoding="utf-8")
    seed_chat(profile, sid="profile-chat")
    apply(source, scan(source), ["profiles"])
    imported_profiles = list((target / "profiles").glob("hermes-*"))
    assert len(imported_profiles) == 1
    assert yaml.safe_load((imported_profiles[0] / "config.yaml").read_text())["model"] == "profile-model"
    with sqlite3.connect(imported_profiles[0] / "state.db") as conn:
        assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 1


def test_unselected_categories_are_untouched(homes):
    source, target = homes
    seed_chat(source)
    apply(source, scan(source), ["settings"])
    assert not (target / "state.db").exists()


def test_wal_conversation_snapshot_never_changes_any_source_file(homes):
    source, target = homes
    seed_chat(source)
    writer = sqlite3.connect(source / "state.db")
    try:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("INSERT INTO messages VALUES (2, 'chat1', 'assistant', 'from WAL', 101)")
        writer.commit()
        before = {p.name: p.read_bytes() for p in source.iterdir() if p.is_file()}
        preview = scan(source)
        apply(source, preview, ["chats"])
        after = {p.name: p.read_bytes() for p in source.iterdir() if p.is_file()}
        assert after == before
        with sqlite3.connect(target / "state.db") as conn:
            assert conn.execute("SELECT content FROM messages ORDER BY id").fetchall() == [("hello",), ("from WAL",)]
    finally:
        writer.close()


def test_skill_reimport_does_not_duplicate_an_initially_empty_target(homes):
    source, target = homes
    (source / "skills" / "demo").mkdir(parents=True)
    (source / "skills" / "demo" / "SKILL.md").write_text("my skill", encoding="utf-8")
    first = apply(source, scan(source), ["skills"])
    second = apply(source, scan(source), ["skills"])
    assert first["imported"]["skills"] == 1
    assert second["imported"]["skills"] == 0
    assert len(list((target / "skills").rglob("SKILL.md"))) == 1


def test_chat_failure_rolls_back_settings_and_existing_transcripts(homes):
    source, target = homes
    seed_chat(source)
    with sqlite3.connect(source / "state.db") as conn:
        conn.execute("DROP TABLE messages")
    original = "model: own-model\n"
    (target / "config.yaml").write_text(original, encoding="utf-8")
    from zeus_state import SessionDB
    db = SessionDB(target / "state.db")
    db.create_session("own", "cli")
    db.close()
    with pytest.raises(sqlite3.Error):
        apply(source, scan(source), ["settings", "chats"])
    assert (target / "config.yaml").read_text() == original
    with sqlite3.connect(target / "state.db") as conn:
        assert conn.execute("SELECT id FROM sessions").fetchall() == [("own",)]


def test_named_profile_cannot_write_sibling_profiles(homes, monkeypatch):
    source, target = homes
    named = target / "profiles" / "work"
    named.mkdir(parents=True)
    monkeypatch.setenv("ZEUS_HOME", str(named))
    preview = scan(source)
    with pytest.raises(ValueError, match="default"):
        apply(source, preview, ["profiles"])
    assert not (named / "profiles").exists()


def test_scan_credentials_in_endpoint_are_not_imported(homes):
    source, target = homes
    (source / "config.yaml").write_text("providers:\n  demo:\n    base_url: https://user:secret@example.invalid/v1?api_key=secret\n", encoding="utf-8")
    apply(source, scan(source), ["settings"])
    assert "secret" not in (target / "config.yaml").read_text()


def test_memory_aliases_both_survive_one_import(homes):
    source, target = homes
    for folder, content in (("memory", "first notes"), ("memories", "second notes")):
        (source / folder).mkdir()
        (source / folder / "MEMORY.md").write_text(content)
    apply(source, scan(source), ["memories"])
    content = (target / "memories" / "MEMORY.md").read_text()
    assert "first notes" in content and "second notes" in content


def test_identical_scan_request_returns_receipt_without_more_writes(homes, monkeypatch):
    source, target = homes
    seed_chat(source)
    preview = scan(source)
    first = apply(source, preview, ["settings", "chats"])
    before = snapshot(target)
    monkeypatch.setattr("zeus_cli.hermes_import.merge_chats", lambda *args, **kwargs: pytest.fail("completed import ran twice"))
    monkeypatch.setattr("zeus_cli.hermes_import.backup_database", lambda *args, **kwargs: pytest.fail("completed import made another backup"))
    second = apply(source, preview, ["chats", "settings"])
    assert second == first
    assert snapshot(target) == before


def test_same_scan_different_selection_has_distinct_receipt(homes):
    source, target = homes
    seed_chat(source)
    preview = scan(source)
    chats = apply(source, preview, ["chats"])
    assert not (target / "config.yaml").exists()
    settings = apply(source, preview, ["settings"])
    assert chats["imported"]["chats"] == 1 and chats["imported"]["settings"] == 0
    assert settings["imported"]["settings"] > 0 and settings["imported"]["chats"] == 0
    assert len(list((target / "imports/hermes/receipts").glob("*.json"))) == 2


def test_completed_receipt_cannot_cross_target_profiles(homes, monkeypatch):
    source, target = homes
    preview = scan(source)
    apply(source, preview, ["settings"])
    other = target.parent / "another-profile"
    other.mkdir()
    monkeypatch.setenv("ZEUS_HOME", str(other))
    with pytest.raises(ValueError, match="profile|preview"):
        apply(source, preview, ["settings"])
    assert not (other / "config.yaml").exists()


def test_completed_receipt_still_requires_the_scanned_source_revision(homes):
    source, _ = homes
    preview = scan(source)
    apply(source, preview, ["settings"])
    (source / "config.yaml").write_text("model: changed-after-import\n", encoding="utf-8")
    with pytest.raises(ValueError, match="changed"):
        apply(source, preview, ["settings"])
