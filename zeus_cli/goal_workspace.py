"""Session terminal context for host-side goal checks."""

from __future__ import annotations


def goal_terminal_backend(session_id: str) -> str:
    """Use the same routed policy and task overrides as terminal execution."""
    from tools.terminal_scope import TerminalPolicyUnavailable, enforce_no_refusal
    from tools.terminal_tool import _get_env_config, resolve_task_overrides

    try:
        enforce_no_refusal()
        config = _get_env_config()
        overrides = resolve_task_overrides(session_id)
        return str(overrides.get("env_type") or config.get("env_type") or "unavailable").strip().lower()
    except (TerminalPolicyUnavailable, ValueError, OSError):
        return "unavailable"


def session_goal_workspace(session_id: str, fallback: str) -> str:
    """A completed terminal command's cwd belongs to its own session, never another's."""
    from tools.terminal_tool import get_session_cwd

    return get_session_cwd(session_id) or fallback
