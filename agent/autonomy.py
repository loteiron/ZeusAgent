"""Explicit, revocable autonomy for one profile and runtime session.

No environment switch or writable permission file: a new process starts with the
normal policy. The transcript records decisions, never a synthetic user answer.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import sys
import threading

from zeus_constants import get_zeus_home

_lock = threading.RLock()
_modes: dict[tuple[str, str], bool] = {}

AUTONOMOUS_INSTRUCTION = (
    "[Autonomous mode enabled by the user for this session]\n"
    "Complete the user's requested work end to end. Inspect the available context, "
    "decide reasonable defaults yourself, implement, verify, and repair failures. "
    "Do not ask questions, seek confirmation, or offer to continue. Record material "
    "assumptions briefly and keep working. Use tools when useful, not for ceremonial "
    "planning or writing chat replies into files. Treat new user messages as steering "
    "unless they replace or cancel the task. Honor explicit constraints and stop commands. "
    "Autonomy authorizes decisions within the user's task; it does not override access "
    "controls or hard deny rules. Never invent credentials, user answers, or test results. "
    "If required access is unavailable, finish independent work and report the precise "
    "blocker without asking a question or claiming completion."
)
_OFF_INSTRUCTION = (
    "[Autonomous mode disabled by the user for this session]\n"
    "The earlier autonomous-mode instruction no longer applies. Use normal decision "
    "and clarification behavior under the current permission policy."
)


def _scope(session_key: str | None = None) -> tuple[str, str]:
    if session_key is None:
        from tools.approval_context import get_current_session_key
        session_key = get_current_session_key(default="")
    return str(get_zeus_home().resolve()), str(session_key or "")


def is_enabled(session_key: str | None = None) -> bool:
    return get_mode(session_key) is True


def get_mode(session_key: str | None = None) -> bool | None:
    """Runtime control snapshot for trusted host IPC; None means never enabled."""
    key = _scope(session_key)
    with _lock:
        return _modes.get(key) if key[1] else None


def _release_mode_dependents(session_key: str) -> None:
    # Avoid loading an optional backend merely to change a decision preference.
    module = sys.modules.get("tools.computer_use.tool")
    if module is not None:
        module.release_computer_use_session(session_key)


def set_mode(session_key: str, enabled: bool) -> None:
    key = _scope(session_key)
    if not key[1]:
        raise ValueError("Autonomous mode requires an active session.")
    with _lock:
        previous = _modes.get(key)
        _modes[key] = bool(enabled)
    if previous != bool(enabled):
        _release_mode_dependents(session_key)


def clear_mode(session_key: str) -> None:
    with _lock:
        previous = _modes.pop(_scope(session_key), None)
    if previous is not None:
        _release_mode_dependents(session_key)


def turn_instruction(session_key: str | None = None) -> str:
    """Snapshot once at turn start; never recompute an already-sent prefix."""
    key = _scope(session_key)
    with _lock:
        enabled = _modes.get(key)
    return "" if enabled is None else AUTONOMOUS_INSTRUCTION if enabled else _OFF_INSTRUCTION


def clarification_result() -> str:
    return json.dumps({"autonomous": True, "asked_user": False,
                       "instruction": AUTONOMOUS_INSTRUCTION})


@dataclass(frozen=True)
class AutonomyCommandResult:
    output: str
    changed: bool = False
    enabled: bool = False
    task: str = ""


def dispatch_autonomy_command(session_key: str, arg: str) -> AutonomyCommandResult:
    arg = arg.strip()
    enabled = is_enabled(session_key)
    if arg.lower() in {"status", "help", "--help", "-h"}:
        return AutonomyCommandResult(
            f"Autonomous mode: {'ON' if enabled else 'OFF'} for this session.\n"
            "/autonom [task] · /autonom on · /autonom off · /autonom status\n"
            "With a task, Zeus works toward a standing goal. /stop cancels work. "
            "A restart or new session restores normal mode.", enabled=enabled)
    enabled = arg.lower() not in {"off", "disable"}
    task = "" if arg.lower() in {"", "on", "enable", "off", "disable"} else arg
    set_mode(session_key, enabled)
    output = ("Autonomous mode ON — I will make decisions, verify the work, and continue "
              "without questions. Applies only to this session." if enabled else
              "Autonomous mode OFF — normal decision and approval policy restored.")
    return AutonomyCommandResult(output, changed=True, enabled=enabled, task=task)
