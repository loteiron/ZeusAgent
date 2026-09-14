"""Default schedules keep working; explicit limits and cancellation still win."""
import pytest

from zeus_cli import goals, loops


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("ZEUS_HOME", str(tmp_path))
    goals._DB_CACHE.clear()
    yield
    goals._DB_CACHE.clear()


def test_loop_survives_former_default_limit_and_restart(isolated_home):
    mgr = loops.LoopManager("unbounded-loop")
    mgr.set("watch the build", interval_seconds=30)
    mgr.state.ticks_fired = 100
    mgr.state.next_due_at = 0
    loops.save_loop(mgr.session_id, mgr.state)
    restored = loops.LoopManager(mgr.session_id)
    assert restored.fire_tick()
    assert restored.state.status == "active"
    assert restored.state.max_ticks == 0
    assert restored.complete_tick("Build is still running")["status"] == "active"


def test_goal_zero_budget_survives_serialization(isolated_home):
    mgr = goals.GoalManager("unbounded-goal")
    mgr.set("finish the work")
    assert mgr.state.max_turns == 0
    restored = goals.GoalState.from_json(mgr.state.to_json())
    assert restored.max_turns == 0


@pytest.mark.parametrize("same_manager", [False, True])
@pytest.mark.parametrize("control", ["pause", "clear", "replace"])
def test_loop_control_wins_over_late_judge(isolated_home, monkeypatch, same_manager, control):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    mgr = loops.LoopManager("race")
    mgr.set("watch old task", until="old task is finished")
    assert mgr.fire_tick()
    entered, release = Event(), Event()

    def judge(*a, **k):
        entered.set()
        assert release.wait(10)
        return "done", "old task done", False, None, False

    monkeypatch.setattr(goals, "judge_goal", judge)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(mgr.complete_tick, "Old task finished")
        try:
            assert entered.wait(10)
            other = mgr if same_manager else loops.LoopManager("race")
            if control == "replace":
                other.set("watch new task")
            else:
                getattr(other, control)()
            expected = loops.load_loop("race").to_json()
        finally:
            release.set()
        future.result(timeout=10)
    assert loops.load_loop("race").to_json() == expected


def test_only_one_scheduler_can_claim_the_tick(isolated_home):
    first = loops.LoopManager("claim")
    first.set("watch build")
    second = loops.LoopManager("claim")
    assert first.fire_tick()
    assert second.fire_tick() is None


def test_idle_recovery_rearms_abandoned_tick_after_restart(isolated_home):
    mgr = loops.LoopManager("crashed-loop")
    mgr.set("watch build")
    assert mgr.fire_tick()
    restored = loops.LoopManager("crashed-loop")
    due = restored.state.next_due_at
    assert not restored.recover_idle_tick(now=due - 1)
    assert restored.recover_idle_tick(now=due + 1)
    assert restored.is_due(now=due + 1)
    assert restored.state.ticks_fired == 1
    assert not restored.state.awaiting_response
