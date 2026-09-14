"""Autonomous decisions must never become fabricated user answers or global grants."""
import json
from unittest.mock import Mock

import pytest

from tools.approval_context import set_current_session_key, reset_current_session_key


@pytest.fixture
def scope(tmp_path, monkeypatch):
    monkeypatch.setenv("ZEUS_HOME", str(tmp_path))
    token = set_current_session_key("owner-chat")
    yield tmp_path
    from agent.autonomy import clear_mode
    clear_mode("owner-chat")
    reset_current_session_key(token)


def test_clarify_returns_decision_to_agent_without_contacting_user(scope):
    from agent.autonomy import set_mode
    from tools.clarify_tool import clarify_tool
    set_mode("owner-chat", True)
    callback = Mock(side_effect=AssertionError("must not ask the user"))
    result = json.loads(clarify_tool("Which framework?", choices=["A", "B"], callback=callback))
    assert result["autonomous"] is True
    assert "user_response" not in result
    assert "decide" in result["instruction"].lower()
    callback.assert_not_called()


def test_grants_are_scoped_and_revocable(scope, monkeypatch):
    from agent.autonomy import is_enabled, set_mode
    from tools.approval import _yolo_active
    set_mode("owner-chat", True)
    assert is_enabled("owner-chat")
    assert _yolo_active()
    assert not is_enabled("different-chat")
    monkeypatch.setenv("ZEUS_HOME", str(scope / "different-profile"))
    assert not is_enabled("owner-chat")
    monkeypatch.setenv("ZEUS_HOME", str(scope))
    set_mode("owner-chat", False)
    assert not is_enabled("owner-chat")


def test_disabling_restores_clarification(scope):
    from agent.autonomy import set_mode
    from tools.clarify_tool import clarify_tool
    set_mode("owner-chat", True)
    set_mode("owner-chat", False)
    result = json.loads(clarify_tool("Which?", callback=lambda *a, **k: "User answer"))
    assert result["user_response"] == "User answer"


def test_computer_use_respects_autonomy_and_revocation(scope, monkeypatch):
    from agent.autonomy import set_mode
    from tools.computer_use import tool
    monkeypatch.setenv("ZEUS_COMPUTER_USE_BACKEND", "noop")
    callback = Mock(return_value="deny")
    monkeypatch.setattr(tool, "_approval_callback", callback)
    set_mode("owner-chat", True)
    result = tool.handle_computer_use({"action": "click", "element": 1}, session_id="owner-chat")
    payload = json.loads(result) if isinstance(result, str) else result
    assert not payload.get("error"), result
    callback.assert_not_called()
    blocked = json.loads(tool.handle_computer_use({"action": "key", "keys": "ctrl+alt+delete"}, session_id="owner-chat"))
    assert "blocked" in blocked["error"]
    callback.assert_not_called()
    set_mode("owner-chat", False)
    denied = json.loads(tool.handle_computer_use({"action": "click", "element": 1}, session_id="owner-chat"))
    assert denied["error"] == "denied by user"
    callback.assert_called_once()


def test_batch_questions_also_return_to_agent(scope):
    from agent.autonomy import set_mode
    from tools.clarify_tool import clarify_tool
    set_mode("owner-chat", True)
    result = json.loads(clarify_tool("", questions=[{"question": "Where?"}], callback=Mock()))
    assert result["autonomous"] is True
    assert "responses" not in result


@pytest.mark.parametrize("kind", ["sudo", "skill_secret"])
def test_missing_credentials_are_reported_without_prompting(scope, monkeypatch, kind):
    from agent.autonomy import set_mode
    callback = Mock(return_value="unexpected password")
    set_mode("owner-chat", True)
    if kind == "sudo":
        from tools import terminal_tool
        from tools.terminal_tool_sudo import _prompt_for_sudo_password
        monkeypatch.setattr(terminal_tool, "_get_sudo_password_callback", lambda: callback)
        assert _prompt_for_sudo_password() == ""
    else:
        from tools import skills_tool
        from tools.skills_tool_setup import _capture_required_environment_variables
        monkeypatch.setattr(skills_tool, "_secret_capture_callback", callback)
        result = _capture_required_environment_variables("example", [{"name": "EXAMPLE_KEY", "prompt": "Key?"}])
        assert result["missing_names"] == ["EXAMPLE_KEY"]
        assert result["setup_skipped"]
    callback.assert_not_called()


def test_enabling_during_legacy_batch_does_not_ask_next_question(scope):
    from agent.autonomy import set_mode
    from tools.clarify_tool import clarify_tool
    asked = []

    def callback(question, choices):
        asked.append(question)
        set_mode("owner-chat", True)
        return ""

    result = json.loads(clarify_tool("", questions=[
        {"question": "Which framework?"}, {"question": "Which database?"},
    ], callback=callback))
    assert asked == ["Which framework?"]
    assert result["autonomous"] is True
