"""Session-owned local verification views; no handler executes a check command."""
from .method_ctx import HandlerRegistry, bind_module

_registry = HandlerRegistry()
method = _registry.method
_profile_scoped = _registry.profile_scoped


def _verification_unavailable(reason: str, cwd="", session_id="") -> dict:
    from agent.verification_report import build_report
    result = build_report([], {"root": cwd, "fingerprint": "", "head": "",
                             "status": "unavailable", "reason": reason, "changed_paths": []},
                        None, status="unknown")
    return {**result, "root": cwd, "session_id": session_id, "changed_paths": []}


@method("verification.status")
@_profile_scoped
def _(rid, params: dict) -> dict:
    from agent.verification_evidence import verification_status
    try:
        session = _sessions.get(params.get("session_id") or "")
        if session:
            with _session_profile_runtime_scope(session):
                cwd = str(session.get("cwd") or "")
                key = str(session.get("session_key") or "")
                if not cwd or _context_cwd_is_launch_artifact(session):
                    result = _verification_unavailable("Choose a workspace to inspect its verification.", cwd, key)
                elif _effective_terminal_backend() != "local":
                    result = _verification_unavailable("Source identity is available for local terminal workspaces.", cwd, key)
                else:
                    result = verification_status(session_id=session.get("session_key"), cwd=cwd)
        else:
            # Retain the existing read-only stored-session query for older clients.
            # Mutations below require a live session and never trust client cwd/key.
            cwd = params.get("cwd")
            result = (verification_status(session_id=params.get("session_key") or params.get("session_id"), cwd=cwd)
                      if isinstance(cwd, str) and cwd else _verification_unavailable("Workspace is unavailable."))
        return _ok(rid, {"verification": result})
    except Exception:
        logger.exception("verification.status failed")
        return _ok(rid, {"verification": _verification_unavailable("Verification could not be inspected.")})


def _verification_baseline_action(rid, params, *, capture: bool):
    session, error = _sess_nowait(params, rid)
    if error:
        return error
    from agent.verification_evidence import capture_verification_baseline, clear_verification_baseline
    try:
        with _session_profile_runtime_scope(session):
            cwd, key = str(session.get("cwd") or ""), str(session.get("session_key") or "")
            if not cwd or not key or _context_cwd_is_launch_artifact(session):
                raise ValueError("Choose a workspace in this session before managing its baseline.")
            if _effective_terminal_backend() != "local":
                raise ValueError("Baseline capture requires a local terminal workspace.")
            if capture:
                return _ok(rid, {"baseline": capture_verification_baseline(session_id=key, cwd=cwd)})
            return _ok(rid, {"cleared": clear_verification_baseline(session_id=key, cwd=cwd)})
    except ValueError as exc:
        return _err(rid, 4004, str(exc))
    except Exception:
        logger.exception("verification baseline action failed")
        return _err(rid, 5031, "Could not update the verification baseline.")


@method("verification.baseline.capture")
@_profile_scoped
def _(rid, params: dict) -> dict:
    return _verification_baseline_action(rid, params, capture=True)


@method("verification.baseline.clear")
@_profile_scoped
def _(rid, params: dict) -> dict:
    return _verification_baseline_action(rid, params, capture=False)


def register(server):
    bind_module(globals(), server, skip=("_",))
