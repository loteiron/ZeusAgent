"""Pure evidence freshness and baseline comparison; exit success is not freshness."""

from __future__ import annotations

import json
from typing import Any


def _snapshot(raw) -> dict:
    try:
        value = json.loads(raw or "{}")
    except (ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def decorate_check(event: dict, workspace: dict, baseline: dict | None, last_edit_at=None) -> dict:
    before = _snapshot(event.pop("workspace_before_json", None))
    after = _snapshot(event.pop("workspace_after_json", None))
    revisions = [snapshot.get("fingerprint") for snapshot in (before, after, workspace)]
    available = all(snapshot.get("status") == "ready" for snapshot in (before, after, workspace))
    if available and all(revisions):
        freshness = "current" if len(set(revisions)) == 1 else "stale"
    elif last_edit_at and last_edit_at > event["created_at"]:
        freshness = "stale"
    else:
        freshness = "unknown"
    previous = baseline.get(event["check_key"]) if baseline is not None else None
    if freshness != "current":
        comparison = "incomparable"
    elif previous is None:
        comparison = "new"
    else:
        comparison = {("passed", "failed"): "regression", ("failed", "passed"): "fixed",
                      ("failed", "failed"): "persistent_failure", ("passed", "passed"): "unchanged"}.get(
                          (previous["status"], event["status"]), "incomparable")
    return {**event, "freshness": freshness, "comparison": comparison,
            "workspace_before": before, "workspace_after": after}


def build_report(events: list[dict], workspace: dict, baseline_row: dict | None,
                 *, status: str | None = None, last_edit_at=None) -> dict[str, Any]:
    baseline = None
    previous = None
    if baseline_row:
        saved = json.loads(baseline_row["checks_json"])
        previous = {check["check_key"]: check for check in saved}
        baseline = {key: baseline_row[key] for key in ("id", "created_at", "fingerprint")}
        baseline["check_count"] = len(saved)
    checks = [decorate_check(event, workspace, previous, last_edit_at) for event in events]
    summary = {"passed": 0, "failed": 0, "stale": 0, "unknown": 0, "total": len(checks)}
    for check in checks:
        key = check["status"] if check["freshness"] == "current" else check["freshness"]
        summary[key if key in summary else "unknown"] += 1
    if status is None:
        status = next((key for key in ("failed", "stale", "unknown") if summary[key]),
                      "passed" if checks else "unverified")
    # The headline evidence explains the aggregate, rather than displaying an unrelated green check.
    evidence = next((c for c in checks if c["freshness"] == status or
                     (c["freshness"] == "current" and c["status"] == status)), checks[0] if checks else None)
    return {"status": status, "evidence": evidence, "checks": checks, "summary": summary,
            "workspace": workspace, "baseline": baseline}
