"""Automation gets the same truthful status with and without quiet output."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.mark.parametrize("quiet", [False, True])
@pytest.mark.parametrize("result,expected", [
    ({"completed": True, "final_response": "done"}, 0),
    ({"completed": False, "failed": True, "error": "connection failed"}, 1),
    ({"completed": False, "failed": True, "final_response": "API failed"}, 1),
    ({"completed": False, "partial": True, "final_response": "unfinished"}, 1),
    ({"completed": False, "interrupted": True, "final_response": "stopped"}, 130),
])
def test_single_query_reports_agent_outcome_and_always_finalizes(monkeypatch, quiet, result, expected):
    import cli as entry
    from zeus_cli.cli_chat_turn_mixin import CLIChatTurnMixin

    class TestCLI(CLIChatTurnMixin):
        pass

    client = TestCLI()
    client.agent = SimpleNamespace(run_conversation=Mock(return_value=result), session_id="test-session")
    client.session_id = "test-session"
    client.conversation_history = []
    client._active_agent_route_signature = "test-route"
    client._ensure_runtime_credentials = Mock(return_value=True)
    client._resolve_turn_agent_config = Mock(return_value={
        "signature": "test-route", "model": "test-model", "runtime": {},
    })
    client._init_agent = Mock(return_value=True)
    client._secret_capture_callback = Mock()
    client._chat_route_images = lambda message, images: message
    client._chat_expand_context_references = lambda message: (message, None)
    client._chat_stage_user_message = Mock()
    client._reset_stream_state = Mock()
    client._chat_setup_turn_audio = Mock()
    client._chat_run_agent = lambda turn, message: setattr(turn, "result", result)

    def wait_for_turn(turn, thread):
        thread.join(timeout=5)
        assert not thread.is_alive()

    client._chat_monitor_agent_thread = wait_for_turn
    client._chat_settle_turn = Mock()
    client._chat_render_turn = lambda turn, *args: turn.result.get("final_response", "Error")
    client._chat_release_turn_audio = Mock()
    client._claim_active_session = Mock(return_value=True)
    client._show_security_advisories = Mock()
    client._print_exit_summary = Mock()
    client.console = Mock()
    finalize = Mock()
    monkeypatch.setattr(entry, "_should_seed_interactive", lambda *args: False)
    monkeypatch.setattr(entry, "_collect_query_images", lambda query, image: (query, []))
    monkeypatch.setattr(entry, "_collect_kanban_task_images", lambda images: [])
    monkeypatch.setattr(entry, "_configure_quiet_agent", Mock())
    monkeypatch.setattr(entry, "set_secret_capture_callback", Mock())
    monkeypatch.setattr(entry, "_finalize_single_query", finalize)
    monkeypatch.delenv("ZEUS_KANBAN_TASK", raising=False)
    monkeypatch.delenv("ZEUS_KANBAN_GOAL_MODE", raising=False)
    try:
        entry._run_single_query_mode(client, "test task", None, quiet, False)
    except SystemExit as exc:
        exit_code = exc.code
    else:
        exit_code = 0
    assert exit_code == expected
    finalize.assert_called_once_with(client)
