"""Shared stop semantics for session-owned goals and recurring work."""


def has_active_schedule(session_id: str) -> bool:
    """Read at turn admission, away from the UI's busy-input dispatch path."""
    if not session_id:
        return False
    from zeus_cli.goals import load_goal
    from zeus_cli.loops import load_loop
    return any(state is not None and state.status == "active"
               for state in (load_goal(session_id), load_loop(session_id)))


def pause_session_schedules(session_id: str) -> bool:
    """Pause durable schedules so a stopped turn cannot wake itself again."""
    if not session_id:
        return False
    from zeus_cli.goals import GoalManager
    from zeus_cli.loops import LoopManager
    from zeus_cli.heartbeat import HeartbeatManager
    paused = False
    for manager in (GoalManager(session_id), LoopManager(session_id), HeartbeatManager(session_id)):
        if manager.state is not None and manager.state.status == "active":
            manager.pause()
            paused = True
    return paused
