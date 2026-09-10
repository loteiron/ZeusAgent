"""CLI boundary for inspecting verification receipts and comparison baselines."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys


def format_evidence_report(report: dict) -> str:
    """Render backend-owned facts without recomputing outcome or freshness."""
    workspace = report.get("workspace") or {}
    lines = [f"Verification: {report['status']}",
             f"Workspace: {workspace.get('root') or report.get('root') or '(unavailable)'}",
             f"Session: {report.get('session_id') or '(unavailable)'}"]
    if workspace.get("reason"):
        lines.append(workspace["reason"])
    summary = report.get("summary") or {}
    if summary:
        lines.append("Checks: {total} total | {passed} passed | {failed} failed | {stale} stale | {unknown} unknown".format(**summary))
    for check in report.get("checks", []):
        lines.extend(["", f"{check['status'].upper()} | {check['freshness']} | {check['comparison']} | {check['scope']}",
                      check["command"], f"Exit: {check['exit_code'] if check['exit_code'] is not None else 'pending'} | {check['created_at']} | {check['cwd']}"])
        if check.get("output_summary"):
            lines.append(check["output_summary"])
    if not report.get("checks"):
        lines.append("No recorded checks for this workspace session. Run your project checks, then use /evidence again.")
    if workspace.get("changed_paths"):
        lines.extend(["", "Changed paths:", *[f"  {item}" for item in workspace["changed_paths"]]])
    if report.get("baseline"):
        lines.append(f"Baseline: {report['baseline']['created_at']} | {report['baseline']['check_count']} checks")
    return "\n".join(lines)


def run_evidence_command(args) -> int | None:
    """None delegates to the recipe runner; report actions never execute a recipe."""
    actions = [name for name in ("status", "capture_baseline", "clear_baseline") if getattr(args, name, False)]
    if not actions:
        return None
    try:
        if len(actions) != 1 or any(getattr(args, key, None) for key in
                                   ("detect_only", "save", "skip_start", "phase", "port")):
            raise ValueError("Choose one evidence action without recipe execution or save options.")
        root = Path(getattr(args, "path", None) or ".").expanduser().resolve()
        if not root.is_dir():
            raise ValueError(f"Workspace directory is unavailable: {root}")
        session = getattr(args, "session", None) or os.environ.get("ZEUS_SESSION_ID") or "default"
        from agent.verification_evidence import (
            capture_verification_baseline, clear_verification_baseline, verification_status,
        )
        if actions[0] == "status":
            report = verification_status(session_id=session, cwd=root)
            payload, code = {"verification": report}, 0 if report["status"] == "passed" else 1
        elif actions[0] == "capture_baseline":
            payload, code = {"baseline": capture_verification_baseline(session_id=session, cwd=root)}, 0
        else:
            payload, code = {"cleared": clear_verification_baseline(session_id=session, cwd=root)}, 0
    except (ValueError, OSError) as exc:
        payload, code = {"error": str(exc)}, 2
    if getattr(args, "json", False):
        print(json.dumps(payload, ensure_ascii=True))
    elif "error" in payload:
        print(f"error: {payload['error']}", file=sys.stderr)
    elif "verification" in payload:
        print(format_evidence_report(payload["verification"]))
    elif "baseline" in payload:
        print(f"Baseline saved: {payload['baseline']['check_count']} checks.")
    else:
        print("Baseline cleared." if payload["cleared"] else "No baseline was saved.")
    return code
