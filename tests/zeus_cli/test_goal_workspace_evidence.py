"""Real workspace and subprocess contracts for goal delivery evidence."""

from pathlib import Path
import subprocess
import sys
import time
from unittest.mock import patch

import pytest

from zeus_cli.goals import GoalGate, GoalManager, load_goal, run_gate, workspace_fingerprint


def _repository(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "value.txt").write_text("initial", encoding="utf-8")
    for args in (["init"], ["add", "."], ["-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "initial"]):
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)
    return root


def _script(tmp_path, content):
    script = tmp_path / "check.py"
    script.write_text(content, encoding="utf-8")
    return f'"{sys.executable}" "{script}"'


def test_fingerprint_distinguishes_two_edits_with_the_same_git_status(tmp_path):
    root = _repository(tmp_path)
    value = root / "value.txt"
    value.write_text("first edit", encoding="utf-8")
    first = workspace_fingerprint(str(root))
    value.write_text("other edit", encoding="utf-8")
    assert first
    assert workspace_fingerprint(str(root)) != first


def test_direct_done_cannot_bypass_an_unrun_required_gate():
    manager = GoalManager("direct-bypass")
    manager.set("verified delivery")
    manager.add_gate("echo checked")
    with pytest.raises(ValueError, match="gate"):
        manager.mark_done("trust me")


def test_dirty_file_repair_reruns_gate_in_persisted_workspace(tmp_path, monkeypatch):
    root = _repository(tmp_path)
    value = root / "value.txt"
    value.write_text("broken", encoding="utf-8")
    failed_fingerprint = workspace_fingerprint(str(root))
    manager = GoalManager("real-workspace", workspace=str(root))
    manager.set("repair the project")
    manager.add_gate(_script(tmp_path, "from pathlib import Path\nimport sys\nprint(Path.cwd())\nsys.exit(0 if Path('value.txt').read_text() == 'repaired' else 1)\n"))
    with patch("zeus_cli.goals.judge_goal", return_value=("done", "repaired", False, None, False)) as judge:
        first = manager.evaluate_after_turn("checking")
        assert first["verdict"] == "gate_failed"
        judge.assert_not_called()
        value.write_text("repaired", encoding="utf-8")
        assert workspace_fingerprint(str(root)) != failed_fingerprint
        monkeypatch.chdir(tmp_path)
        resumed = GoalManager("real-workspace")
        decision = resumed.evaluate_after_turn("fixed")
    assert decision["status"] == "done"
    gate = load_goal("real-workspace").gates[0]
    assert Path(gate.cwd) == root
    assert gate.completed_at >= gate.started_at > 0
    assert gate.duration_ms >= 0
    assert str(root) in gate.last_output_tail
    assert gate.fingerprint_before == gate.fingerprint_after
    assert Path.cwd() == tmp_path


def test_gate_output_cannot_certify_a_workspace_changed_during_check(tmp_path):
    root = _repository(tmp_path)
    manager = GoalManager("mutation", workspace=str(root))
    manager.set("deliver a checked project")
    manager.add_gate(_script(tmp_path, "from pathlib import Path\nPath('value.txt').write_text('mutated')\nprint('passed before mutation')\n"))
    with patch("zeus_cli.goals.judge_goal", return_value=("done", "done", False, None, False)):
        decision = manager.evaluate_after_turn("done")
    assert decision["status"] != "done"
    gate = load_goal("mutation").gates[0]
    assert gate.last_exit_code == 0
    assert gate.freshness == "stale"
    assert gate.fingerprint_before != gate.fingerprint_after


def test_mark_done_requires_current_gate_evidence_even_after_a_previous_pass(tmp_path):
    root = _repository(tmp_path)
    manager = GoalManager("no-bypass", workspace=str(root))
    manager.set("verified delivery")
    manager.add_gate("echo checked")
    with pytest.raises(ValueError, match="gate"):
        manager.mark_done("the model says so")
    with patch("zeus_cli.goals.judge_goal", return_value=("continue", "working", False, None, False)):
        manager.evaluate_after_turn("checking")
    (root / "value.txt").write_text("changed after verification", encoding="utf-8")
    with pytest.raises(ValueError, match="gate"):
        GoalManager("no-bypass").mark_done("reuse prior passing result")
    assert load_goal("no-bypass").status == "active"


def test_completion_rechecks_workspace_after_judge_response(tmp_path):
    root = _repository(tmp_path)
    manager = GoalManager("judge-race", workspace=str(root))
    manager.set("verified delivery")
    manager.add_gate("echo checked")

    def judge(*_args, **_kwargs):
        (root / "value.txt").write_text("edit while judge ran", encoding="utf-8")
        return "done", "looks done", False, None, False

    with patch("zeus_cli.goals.judge_goal", side_effect=judge):
        decision = manager.evaluate_after_turn("done")
    assert decision["status"] != "done"
    assert decision["should_continue"] is True


def test_unknown_workspace_never_counts_as_verified_but_ungated_goals_work(tmp_path):
    manager = GoalManager("unknown", workspace=str(tmp_path))
    manager.set("deliver")
    manager.add_gate("echo checked")
    with patch("zeus_cli.goals.judge_goal", return_value=("done", "done", False, None, False)):
        assert manager.evaluate_after_turn("done")["status"] != "done"
    manager.clear_gates()
    manager.mark_done("no deterministic gate requested")
    assert manager.state.status == "done"


def test_timed_out_gate_terminates_its_descendants(tmp_path):
    import psutil

    marker = tmp_path / "child.pid"
    child = tmp_path / "child.py"
    child.write_text("import os, pathlib, time\npathlib.Path('child.pid').write_text(str(os.getpid()))\ntime.sleep(90)\n", encoding="utf-8")
    command = _script(tmp_path, "import subprocess, sys, time\nsubprocess.Popen([sys.executable, 'child.py'])\ntime.sleep(90)\n")
    passed, code, output = run_gate(GoalGate(command, timeout_seconds=5), cwd=str(tmp_path))
    assert not passed and code == -1
    assert "timed out" in output
    assert marker.exists(), "The descendant must actually start for this cleanup test."
    pid = int(marker.read_text())
    deadline = time.monotonic() + 5
    while psutil.pid_exists(pid) and time.monotonic() < deadline:
        process = psutil.Process(pid)
        if process.status() == psutil.STATUS_ZOMBIE:
            break
        time.sleep(0.05)
    if psutil.pid_exists(pid):
        process = psutil.Process(pid)
        assert process.status() == psutil.STATUS_ZOMBIE, "A timed-out gate leaked a live descendant."
