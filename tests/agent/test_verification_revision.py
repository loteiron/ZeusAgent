"""Content-bound evidence and baseline contracts against real Git workspaces."""

import json
import os
import sqlite3
import subprocess
import sys

import pytest

from agent import verification_evidence as ve


@pytest.fixture
def project(tmp_path, monkeypatch):
    root = tmp_path / "workspace"
    root.mkdir()
    monkeypatch.setenv("ZEUS_HOME", str(tmp_path / "state"))
    (root / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
    (root / "app.py").write_text("value = 1\n", encoding="utf-8")
    (root / ".gitignore").write_text("__pycache__/\n.pytest_cache/\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(["git", "-C", str(root), "-c", "user.name=Test", "-c",
                    "user.email=test@example.invalid", "commit", "-qm", "fixture"], check=True)
    return root


def record(project, command="pytest", code=0, session="s1"):
    from agent.workspace_identity import capture_workspace

    return ve.record_terminal_result(command=command, cwd=project, session_id=session,
                                     exit_code=code, output="check output",
                                     workspace_before=capture_workspace(project))


def status(project, session="s1"):
    return ve.verification_status(session_id=session, cwd=project)


def test_legacy_success_without_before_snapshot_is_unknown(project):
    ve.record_terminal_result(command="pytest", cwd=project, session_id="s1", exit_code=0)
    report = status(project)
    assert report["status"] == "unknown"
    assert report["checks"][0]["freshness"] == "unknown"


def test_targeted_success_does_not_erase_failed_full_suite(project):
    record(project, code=1)
    record(project, "pytest tests/test_app.py", code=0)
    report = status(project)
    assert report["status"] == "failed"
    assert report["summary"] == {"passed": 1, "failed": 1, "stale": 0, "unknown": 0, "total": 2}
    assert {check["scope"] for check in report["checks"]} == {"full", "targeted"}


def test_repeated_actual_check_replaces_itself_only(project):
    record(project, "pytest -k first", code=1)
    record(project, "pytest -k second", code=0)
    record(project, "pytest -k first", code=0)
    report = status(project)
    assert report["status"] == "passed"
    assert len(report["checks"]) == 2


def test_external_edit_invalidates_passing_evidence_without_file_tool(project):
    record(project)
    assert status(project)["status"] == "passed"
    (project / "app.py").write_text("value = 2\n", encoding="utf-8")
    report = status(project)
    assert report["status"] == "stale"
    assert report["checks"][0]["freshness"] == "stale"


def test_edits_during_successful_execution_are_stale(project):
    from agent.workspace_identity import capture_workspace

    before = capture_workspace(project)
    subprocess.run([sys.executable, "-c", "from pathlib import Path; Path('app.py').write_text('value = 3\\n')"],
                   cwd=project, check=True)
    ve.record_terminal_result(command="pytest", cwd=project, session_id="s1", exit_code=0,
                              workspace_before=before)
    assert status(project)["status"] == "stale"


def test_new_result_does_not_refresh_other_stale_checks(project):
    record(project, "pytest -k first")
    record(project, "pytest -k second")
    (project / "app.py").write_text("value = 3\n", encoding="utf-8")
    record(project, "pytest -k first")
    report = status(project)
    assert report["summary"]["passed"] == 1
    assert report["summary"]["stale"] == 1
    assert report["status"] == "stale"


def test_baseline_persists_and_failure_never_becomes_green(project):
    record(project, code=1)
    baseline = ve.capture_verification_baseline(session_id="s1", cwd=project)
    record(project, code=1)
    report = status(project)
    assert report["baseline"]["id"] == baseline["id"]
    assert report["status"] == "failed"
    assert report["checks"][0]["comparison"] == "persistent_failure"
    record(project, code=0)
    assert status(project)["checks"][0]["comparison"] == "fixed"


def test_baseline_detects_regressions_and_new_checks(project):
    record(project)
    ve.capture_verification_baseline(session_id="s1", cwd=project)
    (project / "app.py").write_text("value = 5\n", encoding="utf-8")
    record(project, code=1)
    record(project, "pytest -k extra")
    comparison = {c["command"]: c["comparison"] for c in status(project)["checks"]}
    assert comparison == {"pytest": "regression", "pytest -k extra": "new"}


def test_baseline_rejects_stale_or_missing_evidence(project):
    with pytest.raises(ValueError):
        ve.capture_verification_baseline(session_id="s1", cwd=project)
    record(project)
    (project / "app.py").write_text("value = 8\n", encoding="utf-8")
    with pytest.raises(ValueError):
        ve.capture_verification_baseline(session_id="s1", cwd=project)


def test_baselines_and_checks_are_session_isolated(project):
    record(project)
    ve.capture_verification_baseline(session_id="s1", cwd=project)
    assert status(project, "other")["baseline"] is None
    assert status(project, "other")["checks"] == []
    assert ve.clear_verification_baseline(session_id="other", cwd=project) is False
    assert ve.clear_verification_baseline(session_id="s1", cwd=project) is True
    assert status(project)["baseline"] is None


def test_changed_workspace_makes_baseline_comparison_incomparable(project):
    record(project)
    ve.capture_verification_baseline(session_id="s1", cwd=project)
    (project / "app.py").write_text("value = 10\n", encoding="utf-8")
    assert status(project)["checks"][0]["comparison"] == "incomparable"


def test_old_database_migration_keeps_actual_result_without_fabricating_freshness(project):
    ve.record_terminal_result(command="pytest", cwd=project, session_id="s1", exit_code=0)
    # Simulate a v1 event in the same migrated database.
    with sqlite3.connect(ve._db_path()) as conn:
        conn.execute("UPDATE verification_events SET workspace_before_json=NULL, workspace_after_json=NULL")
    report = status(project)
    assert report["checks"][0]["status"] == "passed"
    assert report["status"] == "unknown"


def test_same_command_in_different_working_directory_is_not_merged(project):
    child = project / "tests"
    child.mkdir()
    record(project)
    record(child)
    assert len(status(project)["checks"]) == 2


def test_output_secrets_are_redacted_before_database_persistence(project):
    from agent.workspace_identity import capture_workspace

    secret = "ghp_" + "a" * 36
    ve.record_terminal_result(command="pytest", cwd=project, session_id="s1", exit_code=1,
                              output=secret, workspace_before=capture_workspace(project))
    assert secret not in json.dumps(status(project))


def test_inflight_check_suppresses_previous_green_until_observed_exit(project):
    record(project)
    before = ve.begin_verification(command="pytest", cwd=project, session_id="s1")
    report = status(project)
    assert report["status"] == "unknown"
    assert report["checks"][0]["status"] == "running"
    with pytest.raises(ValueError):
        ve.capture_verification_baseline(session_id="s1", cwd=project)
    ve.record_terminal_result(command="pytest", cwd=project, session_id="s1", exit_code=0,
                              workspace_before=before)
    assert status(project)["status"] == "passed"


def test_overlapping_identical_checks_wait_for_both_actual_results(project):
    first = ve.begin_verification(command="pytest", cwd=project, session_id="s1")
    second = ve.begin_verification(command="pytest", cwd=project, session_id="s1")
    ve.record_terminal_result(command="pytest", cwd=project, session_id="s1", exit_code=0, workspace_before=second)
    assert status(project)["status"] == "unknown"
    ve.record_terminal_result(command="pytest", cwd=project, session_id="s1", exit_code=1, workspace_before=first)
    assert status(project)["status"] == "failed"


def _executable_check(project, monkeypatch, body="assert True"):
    # pytest executable resolves to the same test runtime, not an unrelated system Python.
    monkeypatch.setenv("PATH", os.path.dirname(sys.executable) + os.pathsep + os.environ["PATH"])
    (project / "test_check.py").write_text("def test_check():\n    " + body + "\n", encoding="utf-8")
    return "pytest -q -p no:cacheprovider test_check.py"


def test_real_foreground_path_captures_before_and_after(project, monkeypatch):
    from tools.environments.local import LocalEnvironment
    from tools.terminal_tool import _ExecPlan, _run_foreground

    command = _executable_check(project, monkeypatch)
    env = LocalEnvironment(cwd=str(project))
    plan = _ExecPlan(config={}, env_type="local", effective_task_id="fg-proof", image="",
                     cwd=str(project), host_cwd=None, effective_timeout=30)
    try:
        response = json.loads(_run_foreground(command, env, plan, task_id="fg-proof", session_id="s1",
                    session_key="fg-proof", workdir=str(project), approval_note=None, clear_interrupt=False))
    finally:
        env.cleanup()
    assert response["exit_code"] == 0, response
    assert response["verification_evidence"]["freshness"] == "current"
    assert status(project)["status"] == "passed"


def test_real_background_path_records_only_after_process_completion(project, monkeypatch):
    from tools.process_registry import ProcessRegistry

    command = _executable_check(project, monkeypatch, "__import__('time').sleep(0.4)")
    registry = ProcessRegistry()
    session = registry.spawn_local(command, cwd=str(project), task_id="bg-proof", verification_session_id="s1")
    assert session._completion_event.wait(30), "background check did not complete"
    assert session.exit_code == 0, session.output_buffer
    report = status(project)
    assert report["status"] == "passed", report
    assert report["checks"][0]["command"] == command


def test_empty_verification_recipe_cannot_pass():
    from agent.verify.runner import VerifyResult

    assert VerifyResult(recipe_name="empty").ok is False


@pytest.mark.parametrize("concurrent", ["other_session", "completed_check", "running_check"])
def test_baseline_source_capture_does_not_lock_evidence_and_rechecks_changes(project, monkeypatch, concurrent):
    from concurrent.futures import ThreadPoolExecutor
    import threading

    record(project)
    snapshot = ve._workspace_snapshot
    entered, release = threading.Event(), threading.Event()
    baseline_thread, captures = None, 0

    def capture(cwd):
        nonlocal captures
        if threading.get_ident() == baseline_thread:
            captures += 1
            if captures == 2:
                entered.set()
                assert release.wait(8)
        return snapshot(cwd)

    def baseline():
        nonlocal baseline_thread
        baseline_thread = threading.get_ident()
        return ve.capture_verification_baseline(session_id="s1", cwd=project)

    def mutate():
        if concurrent == "running_check":
            ve.begin_verification(command="pytest -k next", session_id="s1", cwd=project)
        else:
            record(project, session="s2" if concurrent == "other_session" else "s1")
        return status(project, session="s2" if concurrent == "other_session" else "s1")

    monkeypatch.setattr(ve, "_workspace_snapshot", capture)
    with ThreadPoolExecutor(max_workers=2) as pool:
        saving = pool.submit(baseline)
        try:
            assert entered.wait(5), "second source capture must actually start"
            updating = pool.submit(mutate)
            report = updating.result(timeout=4)
            assert report["status"] == ("unknown" if concurrent == "running_check" else "passed")
        finally:
            release.set()
        if concurrent == "other_session":
            assert saving.result(timeout=5)["check_count"] == 1
        else:
            with pytest.raises(ValueError, match="changed|active"):
                saving.result(timeout=5)
            assert status(project)["baseline"] is None
