"""Goal transitions must reject malformed decisions and survive interrupted storage."""

import json
import sqlite3

import pytest

from zeus_cli import goals
from zeus_state import SessionDB


@pytest.mark.parametrize("payload", [
    {"done": [False]}, {"done": {"value": False}}, {"done": 7},
    {"reason": "no verdict"}, {"verdict": "finished"},
])
def test_invalid_decision_cannot_complete_a_goal(payload):
    verdict, _, parse_failed, directive = goals._parse_judge_response(json.dumps(payload))
    assert verdict == "continue"
    assert parse_failed is True
    assert directive is None


@pytest.mark.parametrize("reason", ['Check {a, b} before continuing.', 'Quoted "}" is evidence.'])
def test_wrapped_json_preserves_braces_inside_reason(reason):
    raw = 'Result:\n' + json.dumps({"verdict": "continue", "reason": reason})
    verdict, parsed_reason, parse_failed, _ = goals._parse_judge_response(raw)
    assert verdict == "continue" and not parse_failed
    assert parsed_reason == reason


def test_failed_goal_migration_keeps_parent_recoverable(tmp_path, monkeypatch):
    db = SessionDB(db_path=tmp_path / "goals.db")
    monkeypatch.setattr(goals, "_get_session_db", lambda: db)
    try:
        goals.save_goal("parent", goals.GoalState(goal="build and verify"))
        # The real SQLite transaction must roll back its first write if its second fails.
        db._conn.execute("""CREATE TRIGGER reject_parent_archive BEFORE UPDATE ON state_meta
            WHEN NEW.key = 'goal:parent' BEGIN SELECT RAISE(ABORT, 'injected archive failure'); END""")
        db._conn.commit()
        assert goals.migrate_goal_to_session("parent", "child") is False
        assert goals.load_goal("parent").status == "active"
        assert goals.load_goal("child") is None
    finally:
        db.close()


def test_goal_migration_can_resume_from_an_independent_connection(tmp_path, monkeypatch):
    path = tmp_path / "goals.db"
    db = SessionDB(db_path=path)
    monkeypatch.setattr(goals, "_get_session_db", lambda: db)
    try:
        goals.save_goal("parent", goals.GoalState(goal="deliver evidence", turns_used=4))
        assert goals.migrate_goal_to_session("parent", "child") is True
        with sqlite3.connect(path) as reader:
            rows = dict(reader.execute("SELECT key, value FROM state_meta WHERE key IN ('goal:parent', 'goal:child')"))
        assert json.loads(rows['goal:parent'])['status'] == 'cleared'
        child = json.loads(rows['goal:child'])
        assert child['status'] == 'active' and child['turns_used'] == 4
        assert goals.migrate_goal_to_session("parent", "child") is False
    finally:
        db.close()
