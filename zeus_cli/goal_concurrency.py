"""Atomic goal writes after slow checks, using the existing SessionDB transaction."""

from __future__ import annotations


class GoalStateChanged(RuntimeError):
    """A user control or another evaluator superseded this result."""


def stored_snapshot(db, key, decode):
    raw = db.get_meta(key)
    return decode(raw).to_json() if raw else None


def save_if_unchanged(db, key, state, expected, decode):
    def write(conn):
        row = conn.execute("SELECT value FROM state_meta WHERE key = ?", (key,)).fetchone()
        current = decode(row[0]).to_json() if row else None
        if current != expected:
            raise GoalStateChanged("Goal changed while its checks were running")
        db.set_meta(key, state.to_json(), cursor=conn.cursor())

    db._execute_write(write)
