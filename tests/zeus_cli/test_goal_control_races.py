"""A slow evaluation never restores work that the user paused, cleared, or replaced."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from threading import Event
from unittest.mock import patch

import pytest

from zeus_cli.goals import GoalManager, load_goal


@pytest.mark.parametrize("stage", ["gate", "judge"])
@pytest.mark.parametrize("control", ["pause", "clear", "replace"])
@pytest.mark.parametrize("same_manager", [False, True])
def test_user_control_wins_while_evaluation_is_running(tmp_path, stage, control, same_manager):
    manager = GoalManager("race", workspace=str(tmp_path))
    manager.set("original goal")
    if stage == "gate":
        manager.add_gate("echo check")
    entered, release = Event(), Event()

    def slow_step(*args, **kwargs):
        entered.set()
        assert release.wait(10), "The test must release the worker"
        return ((True, 0, "check passed") if stage == "gate"
                else ("done", "finished", False, None, False))

    target = "zeus_cli.goals.run_gate" if stage == "gate" else "zeus_cli.goals.judge_goal"
    judge = (patch("zeus_cli.goals.judge_goal", return_value=("done", "finished", False, None, False))
             if stage == "gate" else nullcontext())
    with patch(target, side_effect=slow_step), patch("zeus_cli.goals.workspace_fingerprint", return_value="source-revision"), judge:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(manager.evaluate_after_turn, "finished")
            try:
                assert entered.wait(10), "The gate or judge must actually begin"
                user = manager if same_manager else GoalManager("race")
                if control == "replace":
                    user.set("replacement goal")
                else:
                    getattr(user, control)()
                expected = load_goal("race").to_json()
            finally:
                release.set()
            decision = future.result(timeout=15)
    assert load_goal("race").to_json() == expected
    assert decision["should_continue"] is False
    assert decision["status"] != "done"


@pytest.mark.parametrize("gated", [False, True])
def test_stale_direct_completion_cannot_revive_a_cleared_goal(gated):
    stale = GoalManager("direct-race")
    stale.set("original goal")
    if gated:
        stale.add_gate("echo required")
    GoalManager("direct-race").clear()
    with pytest.raises((ValueError, RuntimeError)):
        stale.mark_done("late completion")
    assert load_goal("direct-race").status == "cleared"


def test_pause_then_resume_invalidates_the_previous_judge_result():
    manager = GoalManager("pause-resume")
    manager.set("original goal")

    def judge(*args, **kwargs):
        user = GoalManager("pause-resume")
        user.pause()
        user.resume()
        return "done", "late result", False, None, False

    with patch("zeus_cli.goals.judge_goal", side_effect=judge):
        decision = manager.evaluate_after_turn("finished")
    assert decision["should_continue"] is False
    assert load_goal("pause-resume").status == "active"


def test_user_pause_between_final_read_and_atomic_write_wins():
    from zeus_cli.goal_concurrency import save_if_unchanged

    manager = GoalManager("atomic-race")
    manager.set("original goal")

    def concurrent_save(*args, **kwargs):
        GoalManager("atomic-race").pause()
        return save_if_unchanged(*args, **kwargs)

    with patch("zeus_cli.goals.judge_goal", return_value=("done", "finished", False, None, False)), \
         patch("zeus_cli.goals.save_if_unchanged", side_effect=concurrent_save):
        decision = manager.evaluate_after_turn("finished")
    assert decision["should_continue"] is False
    assert load_goal("atomic-race").status == "paused"


@pytest.mark.parametrize("control", ["pause", "replace", "pause_resume"])
def test_same_manager_control_wins_during_direct_completion_fingerprint(tmp_path, control):
    manager = GoalManager("direct-shared-race", workspace=str(tmp_path))
    manager.set("original goal")
    manager.add_gate("echo check")
    with patch("zeus_cli.goals.workspace_fingerprint", return_value="source-revision"), \
         patch("zeus_cli.goals.run_gate", return_value=(True, 0, "passed")), \
         patch("zeus_cli.goals.judge_goal", return_value=("continue", "working", False, None, False)):
        manager.evaluate_after_turn("checked")
    entered, release = Event(), Event()

    def slow_fingerprint(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        return "source-revision"

    with patch("zeus_cli.goals.workspace_fingerprint", side_effect=slow_fingerprint):
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(manager.mark_done, "late direct completion")
            try:
                assert entered.wait(10)
                if control == "replace":
                    manager.set("replacement goal")
                else:
                    manager.pause()
                    if control == "pause_resume":
                        manager.resume()
                expected = load_goal(manager.session_id).to_json()
            finally:
                release.set()
            with pytest.raises((ValueError, RuntimeError)):
                future.result(timeout=15)
    assert load_goal(manager.session_id).to_json() == expected


def test_direct_completion_captures_authority_before_cloning_state():
    from zeus_cli.goals import GoalState

    manager = GoalManager("clone-race")
    manager.set("original goal")
    decode = GoalState.from_json
    interrupted = False

    def pause_during_clone(raw):
        nonlocal interrupted
        if not interrupted:
            interrupted = True
            manager.pause()
        return decode(raw)

    with patch.object(GoalState, "from_json", side_effect=pause_during_clone):
        with pytest.raises((ValueError, RuntimeError)):
            manager.mark_done("late result")
    assert load_goal(manager.session_id).status == "paused"
