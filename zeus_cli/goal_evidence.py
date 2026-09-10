"""Workspace-bound delivery evidence for the existing goal quality gates."""

from __future__ import annotations

import os


def normalized_workspace(value: str) -> str:
    return os.path.realpath(os.path.abspath(os.path.expanduser(value))) if value else ""


def gate_freshness(gate, workspace: str, fingerprint: str) -> tuple[str, str]:
    """An exit code is evidence only for the unchanged workspace that produced it."""
    if gate.last_exit_code is None:
        return "not_run", "This check has not run."
    if not workspace or not gate.cwd or not gate.completed_at:
        return "unknown", "This result has no recorded workspace or completion time."
    if os.path.normcase(normalized_workspace(gate.cwd)) != os.path.normcase(normalized_workspace(workspace)):
        return "stale", "The session workspace changed after this check."
    if not fingerprint or not gate.fingerprint_before or not gate.fingerprint_after:
        return "unknown", "The workspace identity could not be verified."
    if gate.fingerprint_before != gate.fingerprint_after:
        return "stale", "Workspace files changed while this check was running."
    if fingerprint != gate.fingerprint_after:
        return "stale", "Workspace files changed after this check."
    return "current", "This result applies to the current workspace."


def gate_snapshot(gate, workspace: str, fingerprint: str) -> dict:
    """Allowlisted evidence; no internal retry cache or arbitrary persisted fields."""
    freshness, reason = gate_freshness(gate, workspace, fingerprint)
    from agent.redact import redact_terminal_output
    return {
        "command": gate.command,
        "timeout_seconds": gate.timeout_seconds,
        "max_retries": gate.max_retries,
        "attempts": gate.attempts,
        "last_exit_code": gate.last_exit_code,
        "last_output_tail": redact_terminal_output(gate.last_output_tail, gate.command, force=True)[-3000:],
        "cwd": gate.cwd,
        "started_at": gate.started_at,
        "completed_at": gate.completed_at,
        "duration_ms": gate.duration_ms,
        "fingerprint_before": gate.fingerprint_before,
        "fingerprint_after": gate.fingerprint_after,
        "freshness": freshness,
        "freshness_reason": reason,
    }
