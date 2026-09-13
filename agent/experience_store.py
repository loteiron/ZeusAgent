"""Profile-local experience from executed checks, with separate causal hypotheses.

An observed recovery is evidence about a command on particular source bytes. It
does not certify an explanation, dependencies, remote services, or future runs.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import unicodedata
import uuid

from zeus_constants import get_zeus_home


_SCHEMA = """
CREATE TABLE IF NOT EXISTS experiences (
    id TEXT PRIMARY KEY, root TEXT NOT NULL, check_key TEXT NOT NULL,
    signature TEXT NOT NULL, symptom TEXT NOT NULL, cause TEXT NOT NULL DEFAULT '',
    resolution TEXT NOT NULL DEFAULT '', state TEXT NOT NULL,
    avoid TEXT NOT NULL DEFAULT '', conditions TEXT NOT NULL DEFAULT '',
    paths_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    recovery_fingerprint TEXT NOT NULL DEFAULT '',
    recovery_count INTEGER NOT NULL DEFAULT 0,
    last_recovery_failure TEXT NOT NULL DEFAULT '', last_verified_at TEXT NOT NULL DEFAULT '',
    counterexample_json TEXT,
    UNIQUE(root, check_key, signature)
);
CREATE TABLE IF NOT EXISTS observations (
    event_key TEXT PRIMARY KEY, experience_id TEXT NOT NULL REFERENCES experiences(id) ON DELETE CASCADE,
    event_id INTEGER NOT NULL, session_id TEXT NOT NULL, created_at TEXT NOT NULL,
    status TEXT NOT NULL, fingerprint TEXT NOT NULL, stable INTEGER NOT NULL,
    receipt_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS experience_root ON experiences(root, updated_at DESC);
CREATE INDEX IF NOT EXISTS experience_observations ON observations(experience_id, created_at);
"""


def _text(value: str, limit: int = 1600) -> str:
    from agent.redact import redact_terminal_output
    from tools.ansi_strip import strip_ansi

    visible = "".join(char for char in strip_ansi(str(value or ""))
                      if char in "\n\t" or not unicodedata.category(char).startswith("C"))
    return redact_terminal_output(visible, "env", force=True)[:limit]


def _diagnostic_excerpt(value: str) -> str:
    """Keep setup context and the final diagnostic when a check produces a long log."""
    output = _text(value, max(1600, len(value or "")))
    if len(output) <= 1600:
        return output
    marker = "\n[... output omitted ...]\n"
    return output[:400] + marker + output[-(1200 - len(marker)):]


def _receipt(event: dict) -> dict:
    before, after = event.get("workspace_before", {}), event.get("workspace_after", {})
    stable = (event.get("exit_code", -1) >= 0 and before.get("status") == after.get("status") == "ready"
              and bool(before.get("fingerprint")) and before.get("fingerprint") == after.get("fingerprint"))
    return {
        "event_id": event["id"], "created_at": event["created_at"],
        "exit_code": event["exit_code"],
        "session_id": event["session_id"], "status": event["status"],
        "command": _text(event["command"], 800), "kind": event["kind"], "scope": event["scope"],
        "output": _diagnostic_excerpt(event.get("output_summary", "")), "fingerprint": after.get("fingerprint", ""),
        "head": after.get("head", ""), "stable": bool(stable),
        "started_at": before.get("_verification_started_at", ""),
        "changed_paths": after.get("changed_paths", [])[:50],
    }


def _failure_signature(symptom):
    # Use diagnostic identities rather than progress counters or wall time. Keep
    # actual expected/observed values: changing those may be a different failure.
    diagnostic = [line.strip() for line in symptom.splitlines() if re.search(
        r"\b(?:[A-Z]\w*)?(?:Error|Exception)\b|^\s*(?:E\s+|FAIL(?:ED|URE)?[ :])", line)]
    basis = "\n".join(dict.fromkeys(diagnostic)) if diagnostic else symptom
    basis = re.sub(r"\b\d+(?:\.\d+)?\s*(?:ms|seconds?|s)\b", "<duration>", basis)
    return hashlib.sha256(basis.encode()).hexdigest()


def _present(row, workspace):
    item = dict(row)
    item["freshness"] = ("unknown" if workspace.get("status") != "ready" or not item["recovery_fingerprint"]
                         else "current" if workspace["fingerprint"] == item["recovery_fingerprint"] else "stale")
    item["causal_explanation"] = "hypothesis"
    item["usable_as_repair"] = item["state"] == "recovered" and item["freshness"] == "current"
    item["evidence_grade"] = ("repeated_recovery" if item["recovery_count"] > 1 else "single_recovery"
                              if item["recovery_count"] else "failure_only")
    item["counterexample"] = json.loads(item.pop("counterexample_json") or "null")
    item["paths"] = json.loads(item.pop("paths_json"))
    return item


class ExperienceStore:
    """Short-lived connections and SQLite transactions isolate profiles and writers."""

    def __init__(self):
        from agent.experience_runtime import settings

        self.path = get_zeus_home() / "experience.db"
        self.settings = settings()

    @contextmanager
    def _connect(self):
        from zeus_state_wal import apply_wal_with_fallback

        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            self.path.chmod(0o600)
            conn.execute("PRAGMA foreign_keys=ON")
            apply_wal_with_fallback(conn, db_label="experience.db")
            conn.executescript(_SCHEMA)
            with conn:
                conn.execute("BEGIN IMMEDIATE")
                yield conn
        finally:
            conn.close()

    def observe(self, event: dict) -> dict | None:
        """Consume one recorded verification outcome; unrelated successes teach nothing."""
        receipt = _receipt(event)
        event_key = hashlib.sha256(json.dumps(
            [event["id"], event["root"], event["session_id"], event["created_at"]]
        ).encode()).hexdigest()
        with self._connect() as conn:
            previous = conn.execute("SELECT experience_id FROM observations WHERE event_key=?", (event_key,)).fetchone()
            if previous:
                return {"id": previous[0], "duplicate": True}
            new_recovery = False
            if event["status"] == "failed":
                symptom = receipt["output"] or "The check exited unsuccessfully without diagnostic output."
                signature = _failure_signature(symptom)
                case = conn.execute("SELECT * FROM experiences WHERE root=? AND check_key=? AND signature=?",
                                    (event["root"], event["check_key"], signature)).fetchone()
                if case is None:
                    case_id = uuid.uuid4().hex[:16]
                    conn.execute("INSERT INTO experiences(id,root,check_key,signature,symptom,state,created_at,updated_at) "
                                 "VALUES (?,?,?,?,?,'unresolved',?,?)",
                                 (case_id, event["root"], event["check_key"], signature, symptom,
                                  event["created_at"], event["created_at"]))
                else:
                    case_id = case["id"]
                    conn.execute("UPDATE experiences SET state='unresolved',updated_at=? WHERE id=?",
                                 (event["created_at"], case_id))
                if receipt["stable"]:
                    conn.execute(
                        "UPDATE experiences SET state='contradicted',counterexample_json=?,updated_at=? "
                        "WHERE root=? AND check_key=? AND recovery_fingerprint=? AND recovery_fingerprint!=''",
                        (json.dumps(receipt), event["created_at"], event["root"], event["check_key"], receipt["fingerprint"]),
                    )
            else:
                recovered = self._recover(conn, event, receipt)
                if recovered is None:
                    return None
                case_id, new_recovery = recovered
            conn.execute("INSERT INTO observations VALUES (?,?,?,?,?,?,?,?,?)",
                         (event_key, case_id, event["id"], event["session_id"], event["created_at"], event["status"],
                          receipt["fingerprint"], receipt["stable"], json.dumps(receipt)))
            if receipt["changed_paths"]:
                conn.execute("UPDATE experiences SET paths_json=? WHERE id=?",
                             (json.dumps([_text(path, 300) for path in receipt["changed_paths"]]), case_id))
            case = conn.execute("SELECT state,resolution,recovery_count FROM experiences WHERE id=?", (case_id,)).fetchone()
            repeats = conn.execute("SELECT count(*) FROM observations WHERE experience_id=? "
                                   "AND fingerprint=? AND stable=1 AND status='failed'",
                                   (case_id, receipt["fingerprint"])).fetchone()[0]
            self._prune(conn, case_id)
            return {"id": case_id, "state": case["state"], "causal_explanation": "hypothesis", "same_source_failures": repeats,
                    "new_recovery": new_recovery, "recovery_count": case["recovery_count"],
                    "needs_explanation": new_recovery and not bool(case["resolution"])}

    def _recover(self, conn, event, receipt):
        failed = conn.execute(
            "SELECT o.*,e.id,e.last_recovery_failure FROM observations o JOIN experiences e ON e.id=o.experience_id "
            "WHERE e.root=? AND e.check_key=? AND o.session_id=? AND o.status='failed' "
            "ORDER BY o.created_at DESC LIMIT 1", (event["root"], event["check_key"], event["session_id"])
        ).fetchone()
        if failed is None:
            # A later session may re-run a known repaired check. It refreshes the
            # observed source identity but must not invent another failure/repair pair.
            prior = conn.execute("SELECT id,updated_at FROM experiences WHERE root=? AND check_key=? AND state='recovered' "
                                 "ORDER BY updated_at DESC LIMIT 1", (event["root"], event["check_key"])).fetchone()
            if prior is None or not receipt["stable"] or receipt["started_at"] < prior["updated_at"]:
                return None
            conn.execute("UPDATE experiences SET recovery_fingerprint=?,last_verified_at=?,updated_at=? WHERE id=?",
                         (receipt["fingerprint"], event["created_at"], event["created_at"], prior["id"]))
            return prior["id"], False
        state = "unverified"
        if receipt["stable"] and failed["stable"] and receipt["started_at"] >= failed["created_at"]:
            state = "unstable" if receipt["fingerprint"] == failed["fingerprint"] else "recovered"
        new_recovery = state == "recovered" and failed["last_recovery_failure"] != failed["event_key"]
        conn.execute("UPDATE experiences SET state=?,updated_at=?,recovery_fingerprint=?, "
                     "recovery_count=recovery_count+?, last_recovery_failure=?,last_verified_at=? WHERE id=?",
                     (state, event["created_at"], receipt["fingerprint"] if state == "recovered" else "", int(new_recovery),
                      failed["event_key"] if state == "recovered" else failed["last_recovery_failure"],
                      event["created_at"] if state == "recovered" else "", failed["id"]))
        return failed["id"], new_recovery

    def _prune(self, conn, case_id):
        # Keep the original failure plus the newest observations. Deleting a case
        # cascades to its copied receipts; the verification ledger is independent.
        conn.execute("DELETE FROM observations WHERE experience_id=? AND event_key NOT IN ("
                     "SELECT event_key FROM observations WHERE experience_id=? ORDER BY created_at DESC LIMIT ?) "
                     "AND event_key NOT IN (SELECT event_key FROM observations WHERE experience_id=? "
                     "AND status='failed' ORDER BY created_at LIMIT 1)",
                     (case_id, case_id, self.settings["observations_per_case"] - 1, case_id))
        conn.execute("DELETE FROM experiences WHERE id NOT IN (SELECT id FROM experiences ORDER BY updated_at DESC LIMIT ?)",
                     (self.settings["max_cases"],))

    def recall(self, *, root, query: str = "", limit: int = 5, workspace: dict | None = None) -> dict:
        """Read only this project's experiences and recompute source freshness."""
        from agent.workspace_identity import capture_workspace

        workspace = workspace if workspace is not None else capture_workspace(root)
        resolved = str(Path(workspace.get("root") or root).resolve())
        if not self.path.exists():
            return {"root": resolved, "experiences": []}
        tokens = set(re.findall(r"\w{3,}", query.casefold()))
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM experiences WHERE root=? ORDER BY updated_at DESC LIMIT ?",
                                (resolved, self.settings["max_cases"])).fetchall()
        matches = []
        for row in rows:
            item = dict(row)
            words = set(re.findall(r"\w{3,}", " ".join(item[k] for k in ("symptom", "cause", "resolution", "avoid", "conditions", "paths_json")).casefold()))
            score = len(tokens & words)
            if tokens and not score:
                continue
            item = _present(item, workspace)
            item["relevance"] = score
            matches.append(item)
        matches.sort(key=lambda item: item["relevance"], reverse=True)
        return {"root": resolved, "experiences": matches[:max(1, min(int(limit), 20))]}

    def root_for_path(self, path: Path) -> str | None:
        """Cheap candidate lookup before paying for source hashing on a file read."""
        if not self.path.exists():
            return None
        with self._connect() as conn:
            roots = [row[0] for row in conn.execute("SELECT DISTINCT root FROM experiences")]
        matches = [root for root in roots if path.is_relative_to(Path(root))]
        return max(matches, key=len) if matches else None

    def show(self, case_id: str, *, root) -> dict:
        from agent.workspace_identity import capture_workspace

        if not self.path.exists():
            raise ValueError("Experience not found in this project and profile.")
        workspace = capture_workspace(root)
        resolved = str(Path(workspace.get("root") or root).resolve())
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM experiences WHERE id=? AND root=?", (case_id, resolved)).fetchone()
            if row is None:
                raise ValueError("Experience not found in this project and profile.")
            receipts = conn.execute("SELECT receipt_json FROM observations WHERE experience_id=? ORDER BY created_at", (case_id,)).fetchall()
        return {**_present(row, workspace), "observations": [json.loads(item[0]) for item in receipts]}

    def explain(self, case_id: str, *, root, cause: str, resolution: str,
                avoid: str = "", conditions: str = "") -> dict:
        """Attach a bounded, redacted explanation without changing observed outcomes."""
        detail = self.show(case_id, root=root)
        if not cause.strip() or not resolution.strip():
            raise ValueError("Both a cause hypothesis and a proposed resolution are required.")
        with self._connect() as conn:
            conn.execute("UPDATE experiences SET cause=?,resolution=?,avoid=?,conditions=? WHERE id=? AND root=?",
                         (_text(cause), _text(resolution), _text(avoid), _text(conditions), case_id, detail["root"]))
        return self.show(case_id, root=root)

    def forget(self, case_id: str, *, root) -> bool:
        """Remove the experience and its copied receipts; original verification remains."""
        detail = self.show(case_id, root=root)
        with self._connect() as conn:
            return conn.execute("DELETE FROM experiences WHERE id=? AND root=?", (case_id, detail["root"])).rowcount > 0
