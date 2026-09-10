"""Status-bar goal segment (⊙ goal N/M) — active-goal-only rendering.

The segment mirrors the desktop composer goal indicator: it appears only
while a /goal is ACTIVE, shows turns used vs the turn budget, and stays out
of the bar entirely for paused/done/absent goals (those already print their
own glyph lines in the conversation thread).
"""

from datetime import datetime, timedelta
import os
import pytest

from cli import ZeusAgentCLI
from zeus_cli.goals import GoalManager


@pytest.fixture(autouse=True)
def isolated_goal_home(tmp_path, monkeypatch):
    monkeypatch.setenv("ZEUS_HOME", str(tmp_path / "zeus"))


def _make_cli(model: str = "anthropic/claude-sonnet-4-20250514"):
    cli_obj = ZeusAgentCLI.__new__(ZeusAgentCLI)
    cli_obj.model = model
    cli_obj.session_start = datetime.now() - timedelta(minutes=14, seconds=32)
    cli_obj.conversation_history = [{"role": "user", "content": "hi"}]
    cli_obj.agent = None
    return cli_obj


def _attach_goal(cli_obj, *, active: bool, turns_used: int = 3, max_turns: int = 20):
    """Exercise the real session/workspace binding used by status refresh."""
    cli_obj.session_id = "sess-goal-test"
    manager = GoalManager(session_id=cli_obj.session_id, workspace=os.getcwd())
    state = manager.set("Render current goal progress", max_turns=max_turns)
    state.turns_used = turns_used
    if not active:
        manager.pause()
    cli_obj._goal_manager = manager
    return cli_obj


class TestStatusBarGoalSegment:
    def test_goal_segment_composition(self):
        cli_obj = _attach_goal(_make_cli(), active=True, turns_used=3, max_turns=20)

        snapshot = cli_obj._get_status_bar_snapshot()

        assert snapshot["goal_active"] is True
        assert snapshot["goal_turns_used"] == 3
        assert snapshot["goal_max_turns"] == 20
        assert cli_obj._status_bar_goal_segment(snapshot) == "⊙ goal 3/20"


    def test_goal_segment_absent_when_paused(self):
        # Paused goals must NOT occupy the status bar (active-only contract).
        cli_obj = _attach_goal(_make_cli(), active=False)

        snapshot = cli_obj._get_status_bar_snapshot()

        assert snapshot["goal_active"] is False
        assert cli_obj._status_bar_goal_segment(snapshot) == ""


    def test_active_goal_rendered_in_wide_status_bar(self):
        cli_obj = _attach_goal(_make_cli(), active=True, turns_used=5, max_turns=20)

        text = cli_obj._build_status_bar_text(width=120)

        assert "⊙ goal 5/20" in text

    def test_active_goal_rendered_in_medium_status_bar(self):
        cli_obj = _attach_goal(_make_cli(), active=True, turns_used=1, max_turns=20)

        text = cli_obj._build_status_bar_text(width=60)

        assert "⊙ goal 1/20" in text

    def test_active_goal_rendered_in_narrow_status_bar(self):
        cli_obj = _attach_goal(_make_cli(), active=True, turns_used=2, max_turns=20)

        text = cli_obj._build_status_bar_text(width=50)

        assert "⊙ goal" in text
