"""Coding verification evidence ledger: records what the agent actually proved in
a code workspace. Deliberately passive — it never runs a suite, never blocks
completion, and never upgrades targeted checks into "repo green"."""

from __future__ import annotations

import hashlib
import json
import re
import shlex
import sqlite3
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

from zeus_constants import get_zeus_home


_DB_LOCK = threading.Lock()
_MAX_OUTPUT_SUMMARY_CHARS = 2000
_MAX_EVIDENCE_AGE_DAYS = 30
_MAX_EVENTS_PER_SESSION_ROOT = 100
_MAX_TOTAL_UNREFERENCED_EVENTS = 10_000
_AD_HOC_SCRIPT_NAME_PREFIXES = ("zeus-verify-", "zeus-ad-hoc-")
_VERIFY_SCHEMA_VERSION = 2

_INTERPRETERS = {"python", "python3", "node", "bash", "sh", "ruby", "perl"}
_TARGET_EXTENSIONS = (".py", ".js", ".jsx", ".ts", ".tsx", ".rs", ".go", ".java")
_TARGET_PREFIXES = ("test_", "tests", "spec", "__tests__")
# Ordered: first matching keyword group wins; "check" only counts when the
# command is not itself a test command; anything else is a test.
_KIND_KEYWORDS = (
    (("lint", "eslint", "ruff"), "lint"),
    (("typecheck", "tsc", "mypy", "pyright", "ty"), "typecheck"), (("build",), "build"),
    (("fmt", "format"), "format"),
)
_PYTEST_SPELLINGS = (
    ["python", "-m", "pytest"], ["python3", "-m", "pytest"],
    ["uv", "run", "pytest"], ["poetry", "run", "pytest"], ["pipenv", "run", "pytest"],
)
_SCHEMA_DDL = (
    """
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """,
    """
        CREATE TABLE IF NOT EXISTS verification_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            session_id TEXT NOT NULL,
            cwd TEXT NOT NULL,
            root TEXT NOT NULL,
            command TEXT NOT NULL,
            canonical_command TEXT NOT NULL,
            kind TEXT NOT NULL,
            scope TEXT NOT NULL,
            status TEXT NOT NULL,
            exit_code INTEGER NOT NULL,
            output_summary TEXT NOT NULL
        )
        """,
    """
        CREATE TABLE IF NOT EXISTS verification_state (
            session_id TEXT NOT NULL,
            root TEXT NOT NULL,
            last_event_id INTEGER,
            last_edit_at TEXT,
            changed_paths_json TEXT NOT NULL DEFAULT '[]',
            PRIMARY KEY (session_id, root)
        )
        """,
    """
        CREATE INDEX IF NOT EXISTS idx_verification_events_session_root
        ON verification_events(session_id, root, id DESC)
        """,
    """CREATE TABLE IF NOT EXISTS verification_checks (
        session_id TEXT NOT NULL, root TEXT NOT NULL, check_key TEXT NOT NULL,
        event_id INTEGER NOT NULL, PRIMARY KEY(session_id, root, check_key))""",
    """CREATE TABLE IF NOT EXISTS verification_baselines (
        session_id TEXT NOT NULL, root TEXT NOT NULL, id TEXT NOT NULL,
        created_at TEXT NOT NULL, fingerprint TEXT NOT NULL, checks_json TEXT NOT NULL,
        PRIMARY KEY(session_id, root))""",
    """CREATE TABLE IF NOT EXISTS verification_active (
        run_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, root TEXT NOT NULL,
        check_key TEXT NOT NULL, event_json TEXT NOT NULL)""",
)


@dataclass(frozen=True)
class _ShellSegment:
    tokens: list[str]
    following_operator: str | None = None


@dataclass(frozen=True)
class VerificationEvidence:
    """A classified command result worth recording."""

    command: str
    canonical_command: str
    kind: str
    scope: str
    status: str
    exit_code: int
    cwd: str
    root: str
    session_id: str
    output_summary: str = ""
    workspace_before_json: str | None = None
    workspace_after_json: str | None = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db_path() -> Path:
    return get_zeus_home() / "verification_evidence.db"


def _connect() -> sqlite3.Connection:
    from zeus_state_wal import apply_wal_with_fallback

    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        apply_wal_with_fallback(conn, db_label="verification_evidence.db")
        conn.execute("PRAGMA busy_timeout=5000")
        _ensure_schema(conn)
    except Exception:
        # A PRAGMA/DDL failure after connect() must not leak the open connection.
        conn.close()
        raise
    return conn


@contextmanager
def _transaction() -> Iterator[sqlite3.Connection]:
    """Open a connection, commit/rollback on exit, and ALWAYS close it.

    ``sqlite3.Connection`` as a context manager only commits/rolls back; without
    the close, each call leaks a connection (and WAL/SHM fds) until GC runs.

    Using ``with _connect()`` alone therefore leaks a connection — and its WAL/SHM file descriptors — on
    every call, deferring the close to the garbage collector, which over a long-running process can exhaust
    ``RLIMIT_NOFILE`` (the cron-ledger sibling of this bug was #69567 / PR #69594).
    """
    conn = _connect()
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def _ensure_schema(conn: sqlite3.Connection) -> None:
    for ddl in _SCHEMA_DDL:
        conn.execute(ddl)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(verification_events)")}
    for column in ("workspace_before_json", "workspace_after_json"):
        if column not in columns:
            conn.execute(f"ALTER TABLE verification_events ADD COLUMN {column} TEXT")
    version = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    if version is None or int(version[0]) < _VERIFY_SCHEMA_VERSION:
        for row in conn.execute("SELECT * FROM verification_events ORDER BY id"):
            conn.execute("INSERT OR REPLACE INTO verification_checks VALUES (?, ?, ?, ?)",
                         (row["session_id"], row["root"], _check_key(row), row["id"]))
    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', ?)",
        (str(_VERIFY_SCHEMA_VERSION),),
    )
    conn.commit()


def _split_shell_segments(command: str, *, posix: bool = True) -> list[_ShellSegment]:
    """Tokenize top-level shell commands while preserving their control operators.

    Returns ``[]`` for anything unparseable (unbalanced quotes, empty segment,
    trailing operator other than ``;``) so callers never match a partial parse.
    """
    raw_segments: list[tuple[str, str | None]] = []
    start = 0
    quote: str | None = None
    escaped = False
    index = 0

    while index < len(command):
        char = command[index]
        if escaped or (char == "\\" and quote != "'"):
            escaped = not escaped  # consume the escaped char / start an escape
            index += 1
            continue
        if quote or char in "'\"":
            quote = None if char == quote else (quote or char)  # close / stay / open
            index += 1
            continue

        operator = None
        if command.startswith(("&&", "||", "|&"), index):
            operator = command[index:index + 2]
        elif char == "\n":
            operator = ";"
        elif char in ";|" or (
            char == "&"
            and (index == 0 or command[index - 1] not in "<>")
            and not command.startswith(("&>", "&>>"), index)
        ):
            operator = char

        if operator is None:
            index += 1
            continue

        raw = command[start:index].strip()
        if not raw:
            return []
        raw_segments.append((raw, operator))
        index += 1 if char == "\n" else len(operator)
        start = index

    if quote or escaped:
        return []
    trailing = command[start:].strip()
    if trailing:
        raw_segments.append((trailing, None))
    elif raw_segments and raw_segments[-1][1] != ";":
        return []

    try:
        segments = [_ShellSegment(shlex.split(raw, posix=posix), operator) for raw, operator in raw_segments]
    except ValueError:
        return []
    return segments if all(s.tokens for s in segments) else []


def _exit_status_is_attributable(segments: list[_ShellSegment], match_index: int, exit_code: int) -> bool:
    """Whether the shell's status proves the matched segment's own status.

    Only the last ``;``-separated sequence reports its status; backgrounding,
    pipes and ``||`` hide it; an ``&&`` chain proves each member only on success.
    """
    if not segments or not 0 <= match_index < len(segments) or any(s.following_operator == "&" for s in segments):
        return False

    sequence_start = max(
        (i + 1 for i, s in enumerate(segments[:-1]) if s.following_operator == ";"), default=0
    )
    if match_index < sequence_start:
        return False

    operators = {segment.following_operator for segment in segments[sequence_start:-1]}
    if operators & {"|", "|&", "||"}:
        return False
    return not operators or (int(exit_code) == 0 and operators == {"&&"})


def _canonical_tokens(canonical: str) -> list[str]:
    """Tokenize a canonical command, stripping leading ``./`` from each token."""
    try:
        return [re.sub(r"^(?:\./)+", "", t.strip()) for t in shlex.split(canonical) if t]
    except ValueError:
        return []


def _strip_command_prefix(tokens: list[str]) -> list[str]:
    """Remove harmless command prefixes (env, VAR=x, command/time/noglob)."""
    i = 1 if tokens and tokens[0] == "env" else 0
    while i < len(tokens) and "=" in tokens[i] and not tokens[i].startswith("-"):
        i += 1
    while i < len(tokens) and tokens[i] in {"command", "time", "noglob"}:
        i += 1
    return list(tokens[i:])


def _equivalent_needles(needle: list[str]) -> list[list[str]]:
    """Return command spellings equivalent to the detected canonical command."""
    candidates = [needle]
    if len(needle) >= 3 and needle[1] == "run" and needle[0] in {"npm", "pnpm", "yarn", "bun"}:
        candidates.append([needle[0], needle[2]])
    if len(needle) == 1 and "/" in needle[0]:
        candidates += [["bash", needle[0]], ["sh", needle[0]]]
    if needle == ["pytest"]:
        candidates += _PYTEST_SPELLINGS
    return candidates


def _find_canonical_match(command: str, canonical_commands: list[str], exit_code: int) -> Optional[tuple[str, list[str]]]:
    """Return ``(canonical, trailing_args)`` for the first detected command."""
    for posix in (True, False):
        segments = _split_shell_segments(command, posix=posix)
        for canonical in canonical_commands:
            needle = _canonical_tokens(canonical)
            if not needle:
                continue
            for index, segment in enumerate(segments):
                candidate_tokens = _strip_command_prefix(segment.tokens)
                if candidate_tokens:
                    executable = candidate_tokens[0].strip("\"'").replace("\\", "/").rsplit("/", 1)[-1].lower()
                    if re.fullmatch(r"python(?:\d(?:\.\d+)?)?(?:\.exe)?", executable):
                        candidate_tokens[0] = "python"
                    elif executable.removesuffix(".exe").removesuffix(".cmd") in {"pytest", "npm", "pnpm", "yarn", "bun", "uv"}:
                        candidate_tokens[0] = executable.removesuffix(".exe").removesuffix(".cmd")
                for candidate in _equivalent_needles(needle):
                    if candidate_tokens[:len(candidate)] == candidate and _exit_status_is_attributable(segments, index, exit_code):
                        return canonical, candidate_tokens[len(candidate):]
    return None


def _kind_for_command(canonical: str) -> str:
    lowered = canonical.lower()
    kind = next((k for words, k in _KIND_KEYWORDS if any(w in lowered for w in words)), None)
    return kind or ("check" if "check" in lowered and "test" not in lowered else "test")


def _looks_like_target(arg: str) -> bool:
    return bool(arg) and not arg.startswith("-") and "=" not in arg and (
        any(m in arg for m in ("/", "\\", "::")) or arg.endswith(_TARGET_EXTENSIONS) or arg.startswith(_TARGET_PREFIXES)
    )


def _is_under(token: str, base: str | Path | None) -> bool:
    """Whether absolute path ``token`` is ``base`` or lies beneath it (resolved)."""
    if not base:
        return False
    try:
        path = Path(token).expanduser()
        if not path.is_absolute():
            return False
        resolved, base_path = path.resolve(), Path(base).expanduser().resolve()
        return resolved == base_path or base_path in resolved.parents
    except Exception:
        return False


def _is_temp_script_path(token: str, root: str | Path | None) -> bool:
    """An ad-hoc verify script: prefixed name, under the temp dir, outside the repo."""
    try:
        name = Path(token).expanduser().name
    except Exception:
        return False
    return name.startswith(_AD_HOC_SCRIPT_NAME_PREFIXES) and _is_under(token, tempfile.gettempdir()) and not _is_under(token, root)


def _ad_hoc_script_args(tokens: list[str], root: str | Path | None) -> Optional[list[str]]:
    candidate_tokens = _strip_command_prefix(tokens)
    if not candidate_tokens:
        return None
    command = candidate_tokens[0]
    if _is_temp_script_path(command, root):
        return candidate_tokens[1:]
    if command in _INTERPRETERS:
        # Skip interpreter flags; the first positional must be the script.
        for idx, token in enumerate(candidate_tokens[1:], start=1):
            if _is_temp_script_path(token, root):
                return candidate_tokens[idx + 1:]
            if token != "--" and not token.startswith("-"):
                return None
    return None


def _find_ad_hoc_match(command: str, root: str | Path | None, exit_code: int = 0) -> Optional[list[str]]:
    # posix=False is retried so Windows backslash script paths survive splitting.
    for posix in (True, False):
        segments = _split_shell_segments(command, posix=posix)
        for index, segment in enumerate(segments):
            trailing_args = _ad_hoc_script_args(segment.tokens, root)
            if trailing_args is not None and _exit_status_is_attributable(segments, index, exit_code):
                return trailing_args
    return None


def _summarize_output(output: str) -> str:
    text = (output or "").strip()
    if len(text) <= _MAX_OUTPUT_SUMMARY_CHARS:
        return text
    head = _MAX_OUTPUT_SUMMARY_CHARS // 3
    return (
        f"{text[:head]}\n... [{len(text) - _MAX_OUTPUT_SUMMARY_CHARS} chars omitted] ...\n"
        f"{text[head - _MAX_OUTPUT_SUMMARY_CHARS:]}"
    )


def _prune_old_events(conn: sqlite3.Connection, *, session_id: str, root: str) -> None:
    """Bound ledger growth without deleting the current state pointer.

    Order matters: per-(session, root) cap, expire stale state rows, then expire
    old events and cap the total — never dropping an event still referenced
    by a ``verification_state.last_event_id``.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=_MAX_EVIDENCE_AGE_DAYS)).isoformat()
    conn.execute(
        "DELETE FROM verification_events WHERE session_id = ? AND root = ? AND id NOT IN ("
        " SELECT id FROM verification_events WHERE session_id = ? AND root = ?"
        " ORDER BY id DESC LIMIT ?) AND id NOT IN (SELECT event_id FROM verification_checks)",
        (session_id, root, session_id, root, _MAX_EVENTS_PER_SESSION_ROOT),
    )
    conn.execute(
        "DELETE FROM verification_state"
        " WHERE (last_edit_at IS NOT NULL AND last_edit_at < ?)"
        " OR (last_edit_at IS NULL AND last_event_id IN ("
        " SELECT id FROM verification_events WHERE created_at < ?))",
        (cutoff, cutoff),
    )
    conn.execute(
        "DELETE FROM verification_events WHERE created_at < ? AND id NOT IN ("
        " SELECT last_event_id FROM verification_state WHERE last_event_id IS NOT NULL)"
        " AND id NOT IN (SELECT event_id FROM verification_checks)",
        (cutoff,),
    )
    conn.execute(
        "DELETE FROM verification_events WHERE id NOT IN ("
        " SELECT id FROM verification_events ORDER BY id DESC LIMIT ?)"
        " AND id NOT IN ("
        " SELECT last_event_id FROM verification_state WHERE last_event_id IS NOT NULL)"
        " AND id NOT IN (SELECT event_id FROM verification_checks)",
        (_MAX_TOTAL_UNREFERENCED_EVENTS,),
    )


def _project_facts(cwd: str | Path | None) -> Optional[dict[str, Any]]:
    """Workspace facts for ``cwd``; ``None`` when detection fails or finds nothing."""
    try:
        from agent.coding_context import project_facts_for

        return project_facts_for(cwd)
    except Exception:
        return None


def _root_for(facts: dict[str, Any] | None, cwd: str | Path | None) -> str:
    return str((facts or {}).get("root") or Path(cwd or ".").resolve())


def _load_changed_paths(raw: Any) -> list[Any]:
    try:
        return json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []


def classify_verification_command(
    command: str, *, cwd: str | Path | None = None, session_id: str | None = None, exit_code: int = 0, output: str = ""
) -> Optional[VerificationEvidence]:
    """Classify a terminal command as verification evidence, if applicable.

    Ad-hoc temp scripts only count when the project has no canonical verify
    commands at all, so they never shadow a real suite.
    """
    if not command or not isinstance(command, str):
        return None
    facts = _project_facts(cwd)
    if not facts:
        return None

    verify_commands = list(facts.get("verifyCommands") or [])
    match = _find_canonical_match(command, verify_commands, int(exit_code))
    if match is not None:
        canonical, trailing_args = match
        kind = _kind_for_command(canonical)
        selecting = {"-k", "-m", "-t", "--lf", "--last-failed", "--deselect", "--ignore", "--testNamePattern"}
        scope = "targeted" if any(map(_looks_like_target, trailing_args)) or any(
            arg.split("=", 1)[0] in selecting for arg in trailing_args) else "full"
    else:
        if verify_commands or _find_ad_hoc_match(command, facts.get("root"), int(exit_code)) is None:
            return None
        canonical, kind, scope = "ad-hoc verification script", "ad_hoc", "targeted"
    return VerificationEvidence(
        command=command, canonical_command=canonical, kind=kind, scope=scope,
        status="passed" if int(exit_code) == 0 else "failed", exit_code=int(exit_code),
        cwd=str(Path(cwd or ".").resolve()), root=_root_for(facts, cwd),
        session_id=str(session_id or "default"), output_summary=_summarize_output(output),
    )


def record_terminal_result(
    *, command: str, cwd: str | Path | None, session_id: str | None, exit_code: int, output: str = "",
    workspace_before: dict[str, Any] | None = None,
    workspace_after: dict[str, Any] | None = None,
) -> Optional[dict[str, Any]]:
    """Record a foreground terminal result when it is verification evidence."""
    evidence = classify_verification_command(command, cwd=cwd, session_id=session_id, exit_code=exit_code, output=output)
    if evidence is None:
        return None
    evidence = replace(evidence,
        workspace_before_json=json.dumps(workspace_before) if workspace_before is not None else None,
        workspace_after_json=json.dumps(workspace_after or _workspace_snapshot(cwd)))
    return _insert_evidence(evidence)


def record_verify_run(
    *, root: str | Path, session_id: str | None = None, ok: bool, command: str = "zeus verify",
    scope: str = "full", output: str = "", workspace_before: dict[str, Any] | None = None,
    workspace_after: dict[str, Any] | None = None,
) -> Optional[dict[str, Any]]:
    """Record a completed ``zeus verify`` run as verification evidence.

    A pass marks the workspace ``passed`` for the verify-on-stop guard like a
    canonical test command would. ``root`` is re-resolved through project facts
    so it matches what :func:`verification_status` derives later.
    """
    resolved = str(Path(root).resolve())
    return _insert_evidence(VerificationEvidence(
        command=command, canonical_command="zeus verify", kind="verify",
        scope=scope if scope in {"full", "targeted"} else "full",
        status="passed" if ok else "failed", exit_code=0 if ok else 1, cwd=resolved,
        root=str((_project_facts(root) or {}).get("root") or resolved),
        session_id=str(session_id or "default"), output_summary=_summarize_output(output),
        workspace_before_json=json.dumps(workspace_before) if workspace_before is not None else None,
        workspace_after_json=json.dumps(workspace_after or _workspace_snapshot(root)),
    ))


def _insert_evidence(evidence: VerificationEvidence) -> dict[str, Any]:
    """Insert a classified evidence row and repoint the workspace state."""
    created_at = _utc_now()
    e = evidence
    from agent.redact import redact_terminal_output
    check_key = _check_key(e.__dict__)
    command = redact_terminal_output(e.command, "env")
    output = redact_terminal_output(e.output_summary, "env")
    with _DB_LOCK, _transaction() as conn:
        cur = conn.execute(
            "INSERT INTO verification_events("
            " created_at, session_id, cwd, root, command, canonical_command,"
            " kind, scope, status, exit_code, output_summary, workspace_before_json, workspace_after_json"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (created_at, e.session_id, e.cwd, e.root, command, e.canonical_command, e.kind, e.scope,
             e.status, e.exit_code, output, e.workspace_before_json, e.workspace_after_json),
        )
        if cur.lastrowid is None:
            raise RuntimeError("verification event insert did not return an id")
        event_id = int(cur.lastrowid)
        conn.execute("INSERT OR REPLACE INTO verification_checks VALUES (?, ?, ?, ?)",
                     (e.session_id, e.root, check_key, event_id))
        run_id = _parse_snapshot(e.workspace_before_json).get("_verification_run_id")
        if run_id:
            conn.execute("DELETE FROM verification_active WHERE run_id=? AND session_id=? AND root=?",
                         (run_id, e.session_id, e.root))
        conn.execute(
            "INSERT INTO verification_state("
            " session_id, root, last_event_id, last_edit_at, changed_paths_json"
            ") VALUES (?, ?, ?, NULL, '[]')"
            " ON CONFLICT(session_id, root) DO UPDATE SET"
            " last_event_id = excluded.last_event_id",
            (e.session_id, e.root, event_id),
        )
        _prune_old_events(conn, session_id=e.session_id, root=e.root)
        conn.commit()

    from agent.verification_report import decorate_check
    event = {"id": event_id, **e.__dict__, "created_at": created_at, "check_key": check_key,
             "command": command, "output_summary": output}
    return decorate_check(event, _parse_snapshot(e.workspace_after_json), None)


def mark_workspace_edited(
    *, session_id: str | None, cwd: str | Path | None, paths: list[str] | tuple[str, ...] | None = None
) -> Optional[dict[str, Any]]:
    """Mark verification evidence stale after a successful file edit."""
    facts = _project_facts(cwd)
    if not facts:
        return None

    sid = str(session_id or "default")
    root = _root_for(facts, cwd)
    changed_paths = sorted({str(p) for p in (paths or []) if p})
    edited_at = _utc_now()

    with _DB_LOCK, _transaction() as conn:
        row = conn.execute(
            "SELECT changed_paths_json FROM verification_state WHERE session_id = ? AND root = ?",
            (sid, root),
        ).fetchone()
        # Merge with what was already recorded, bounded to the last 200 paths.
        existing = _load_changed_paths(row["changed_paths_json"]) if row is not None else []
        merged = sorted(set(existing) | set(changed_paths))[-200:]
        conn.execute(
            "INSERT INTO verification_state("
            " session_id, root, last_event_id, last_edit_at, changed_paths_json"
            ") VALUES (?, ?, NULL, ?, ?)"
            " ON CONFLICT(session_id, root) DO UPDATE SET"
            " last_edit_at = excluded.last_edit_at,"
            " changed_paths_json = excluded.changed_paths_json",
            (sid, root, edited_at, json.dumps(merged)),
        )
        conn.commit()

    return {"session_id": sid, "root": root, "last_edit_at": edited_at, "changed_paths": changed_paths}


def _check_key(event) -> str:
    payload = [event["command"], event["cwd"], event["scope"]]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode("utf-8")).hexdigest()


def _workspace_snapshot(cwd) -> dict[str, Any]:
    from agent.workspace_identity import capture_workspace

    return capture_workspace(cwd)


def _parse_snapshot(raw) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
    except (ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def begin_verification(*, command: str, cwd, session_id: str | None, local: bool = True) -> dict | None:
    """Capture before execution, after approval. Remote paths are never hashed on the host."""
    evidence = classify_verification_command(command, cwd=cwd, session_id=session_id)
    if evidence is None:
        return None
    return _begin_evidence(evidence, local=local)


def begin_verify_run(*, root, session_id: str | None, command="zeus verify", scope="full") -> dict:
    resolved = str(Path(root).resolve())
    evidence = VerificationEvidence(command=command, canonical_command="zeus verify", kind="verify",
        scope=scope, status="running", exit_code=-1, cwd=resolved,
        root=_root_for(_project_facts(root), root), session_id=str(session_id or "default"))
    return _begin_evidence(evidence)


def _begin_evidence(evidence, *, local=True) -> dict:
    import uuid
    from agent.redact import redact_terminal_output

    if not local:
        workspace = {"root": evidence.root, "status": "unavailable", "fingerprint": "",
                     "reason": "The command runs remotely; local content is not execution evidence."}
    else:
        workspace = _workspace_snapshot(evidence.cwd)
    run_id = str(uuid.uuid4())
    workspace["_verification_run_id"] = run_id
    event = {**evidence.__dict__, "id": "running:" + run_id, "created_at": _utc_now(),
             "status": "running", "exit_code": None, "check_key": _check_key(evidence.__dict__),
             "command": redact_terminal_output(evidence.command, "env"),
             "workspace_before_json": json.dumps(workspace)}
    with _DB_LOCK, _transaction() as conn:
        conn.execute("INSERT INTO verification_active VALUES (?, ?, ?, ?, ?)",
                     (run_id, evidence.session_id, evidence.root, event["check_key"], json.dumps(event)))
    return workspace


def verification_status(*, session_id: str | None, cwd: str | Path | None) -> dict[str, Any]:
    """Aggregate current results per exact command/cwd/scope without hiding failures."""
    from agent.verification_report import build_report

    facts = _project_facts(cwd)
    workspace = _workspace_snapshot(_root_for(facts, cwd))

    sid = str(session_id or "default")
    root = _root_for(facts, cwd)
    with _DB_LOCK, _transaction() as conn:
        state = conn.execute(
            "SELECT last_event_id, last_edit_at, changed_paths_json"
            " FROM verification_state WHERE session_id = ? AND root = ?",
            (sid, root),
        ).fetchone()
        events = conn.execute("SELECT e.*, c.check_key FROM verification_checks c"
                              " JOIN verification_events e ON e.id=c.event_id"
                              " WHERE c.session_id=? AND c.root=? ORDER BY e.id DESC", (sid, root)).fetchall()
        baseline = conn.execute("SELECT * FROM verification_baselines WHERE session_id=? AND root=?", (sid, root)).fetchone()
        active = conn.execute("SELECT event_json FROM verification_active WHERE session_id=? AND root=?",
                              (sid, root)).fetchall()
    active_events = {event["check_key"]: event for event in (json.loads(row[0]) for row in active)}
    all_events = list(active_events.values()) + [dict(e) for e in events if e["check_key"] not in active_events]
    result = build_report(all_events, workspace, dict(baseline) if baseline else None,
                          status="not_applicable" if not facts and not all_events else None,
                          last_edit_at=state["last_edit_at"] if state else None)
    result.update(root=root, session_id=sid,
                  changed_paths=_load_changed_paths(state["changed_paths_json"]) if state else [])
    return result


def capture_verification_baseline(*, session_id: str | None, cwd) -> dict[str, Any]:
    """Pin current observed outcomes, including failures; never infer missing results."""
    import uuid

    report = verification_status(session_id=session_id, cwd=cwd)
    if not report["checks"] or any(c["freshness"] != "current" or c["status"] not in {"passed", "failed"}
                                   for c in report["checks"]):
        raise ValueError("Run every check on the current workspace before capturing a baseline.")
    snapshot = report["workspace"]
    if not snapshot.get("fingerprint"):
        raise ValueError("A baseline requires an available workspace fingerprint.")
    checks = [{key: check[key] for key in ("check_key", "status", "command", "cwd", "scope", "id")}
              for check in report["checks"]]
    baseline = {"id": str(uuid.uuid4()), "created_at": _utc_now(), "fingerprint": snapshot["fingerprint"],
                "check_count": len(checks)}
    # Source reads can take seconds and are independent of the evidence DB.
    # Holding its lock cannot make filesystem edits atomic with this snapshot.
    refreshed = _workspace_snapshot(report["root"])
    if refreshed.get("status") != "ready" or refreshed.get("fingerprint") != snapshot["fingerprint"]:
        raise ValueError("Workspace changed while capturing the baseline; rerun checks.")
    with _DB_LOCK, _transaction() as conn:
        # Reserve the write before reading IDs, including against other processes.
        conn.execute("BEGIN IMMEDIATE")
        current = conn.execute("SELECT event_id FROM verification_checks WHERE session_id=? AND root=?",
                               (report["session_id"], report["root"])).fetchall()
        if {r[0] for r in current} != {c["id"] for c in checks}:
            raise ValueError("Verification changed while capturing the baseline; retry.")
        if conn.execute("SELECT 1 FROM verification_active WHERE session_id=? AND root=? LIMIT 1",
                        (report["session_id"], report["root"])).fetchone():
            raise ValueError("A verification run is active; wait for its observed result.")
        conn.execute("INSERT OR REPLACE INTO verification_baselines VALUES (?, ?, ?, ?, ?, ?)",
                     (report["session_id"], report["root"], baseline["id"], baseline["created_at"],
                      baseline["fingerprint"], json.dumps(checks)))
    return baseline


def clear_verification_baseline(*, session_id: str | None, cwd) -> bool:
    root = _root_for(_project_facts(cwd), cwd)
    with _DB_LOCK, _transaction() as conn:
        result = conn.execute("DELETE FROM verification_baselines WHERE session_id=? AND root=?",
                              (str(session_id or "default"), root))
    return bool(result.rowcount)
