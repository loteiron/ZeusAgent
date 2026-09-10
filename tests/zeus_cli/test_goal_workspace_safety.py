"""Goal checks follow routed terminal policy, cwd changes, and output privacy."""

from pathlib import Path
from unittest.mock import patch

import pytest

from zeus_cli.goal_evidence import gate_snapshot
from zeus_cli.goals import GoalGate, GoalManager, load_goal


@pytest.mark.parametrize("backend", ["ssh", "docker"])
def test_remote_session_never_runs_a_gate_on_an_existing_host_path(tmp_path, backend):
    from tools.terminal_scope import reset_terminal_scope, set_terminal_scope

    scope = set_terminal_scope({"TERMINAL_ENV": backend})
    try:
        manager = GoalManager("remote-check", workspace=str(tmp_path))
        manager.set("check the remote source")
        manager.add_gate("echo must-not-run")
        with patch("zeus_cli.goals.run_gate") as run, patch("zeus_cli.goals.judge_goal") as judge:
            decision = manager.evaluate_after_turn("done")
        assert decision["status"] == "paused"
        assert decision["verdict"] == "gate_unverified"
        run.assert_not_called()
        judge.assert_not_called()
        with pytest.raises(ValueError, match="local terminal"):
            manager.mark_done("skip the backend restriction")
    finally:
        reset_terminal_scope(scope)


def test_refused_terminal_policy_and_remote_tilde_do_not_become_host_workspaces():
    from tools.terminal_scope import TerminalPolicyRefusal, reset_terminal_scope, set_terminal_scope

    scope = set_terminal_scope(TerminalPolicyRefusal("profile unavailable"))
    try:
        manager = GoalManager("refused", workspace="~")
        manager.set("check the source")
        manager.add_gate("echo must-not-run")
        assert manager.state.workspace == "~"
        with patch("zeus_cli.goals.run_gate") as run:
            assert manager.evaluate_after_turn("done")["verdict"] == "gate_unverified"
        run.assert_not_called()
    finally:
        reset_terminal_scope(scope)


def test_gate_output_is_redacted_before_persistence_and_for_legacy_views(tmp_path):
    secret = "ghp_" + "A" * 36
    manager = GoalManager("private-evidence", workspace=str(tmp_path))
    manager.set("check source")
    manager.add_gate("echo output")
    with patch("zeus_cli.goals.run_gate", return_value=(False, 1, f"failed token: {secret}")):
        decision = manager.evaluate_after_turn("checking")
    assert secret not in decision["continuation_prompt"]
    assert secret not in load_goal("private-evidence").to_json()
    legacy = GoalGate("echo output", last_exit_code=1, last_output_tail=secret)
    assert secret not in gate_snapshot(legacy, str(tmp_path), "")["last_output_tail"]


def test_cached_cli_manager_follows_an_intentional_directory_change(tmp_path, monkeypatch):
    from zeus_cli.cli_loops_mixin import CLILoopsMixin

    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    cli = object.__new__(CLILoopsMixin)
    cli.session_id = "moved-cli"
    monkeypatch.chdir(first)
    manager = cli._get_goal_manager()
    manager.set("deliver work here")
    monkeypatch.chdir(second)
    same_manager = cli._get_goal_manager()
    assert same_manager is manager
    assert Path(same_manager.state.workspace) == second
    assert Path.cwd() == second


def test_gateway_workspace_uses_own_session_record_over_another_profile_default(tmp_path):
    from tools.terminal_scope import reset_terminal_scope, set_terminal_scope
    from tools.terminal_tool import clear_session_cwd, record_session_cwd
    from zeus_cli.goal_workspace import session_goal_workspace, goal_terminal_backend

    own = str(tmp_path / "own")
    other = str(tmp_path / "other")
    record_session_cwd("session-a", own)
    record_session_cwd("session-b", other)
    scope = set_terminal_scope({"TERMINAL_ENV": "local", "TERMINAL_CWD": other})
    try:
        assert goal_terminal_backend("session-a") == "local"
        assert session_goal_workspace("session-a", other) == own
        assert session_goal_workspace("session-b", own) == other
    finally:
        reset_terminal_scope(scope)
        clear_session_cwd("session-a")
        clear_session_cwd("session-b")
