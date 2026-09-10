"""Exercise the actual outer loop against bounded synthetic provider outcomes."""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from tests.run_agent.test_run_agent import _mock_response


@pytest.fixture
def agent(tmp_path):
    from run_agent import AIAgent
    from zeus_state import SessionDB

    db = SessionDB(db_path=tmp_path / "sessions.db")
    with (patch("model_tools.get_tool_definitions", return_value=[]),
          patch("model_tools.check_toolset_requirements", return_value={}),
          patch("agent.process_bootstrap.OpenAI")):
        value = AIAgent(session_db=db, api_key="test", base_url="http://127.0.0.1:1/v1", model="test/model",
                        provider="openai-compat", quiet_mode=True, skip_context_files=True, skip_memory=True)
    value.client = MagicMock()
    value._cached_system_prompt = "You are helpful."
    value._use_prompt_caching = False
    value.compression_enabled = False
    value.save_trajectories = False
    value._api_max_retries = 2
    with (patch.object(value, "_persist_session"), patch.object(value, "_save_trajectory"),
          patch.object(value, "_cleanup_task_resources")):
        try:
            yield value
        finally:
            db.close()


@pytest.mark.parametrize("restart_flag", ["restart_with_redirected_messages", "restart_with_rebuilt_messages"])
def test_refunded_restarts_are_bounded_per_turn_and_next_turn_can_run(agent, restart_flag):
    attempts = 0

    def interrupted_attempt(instance, state):
        nonlocal attempts
        attempts += 1
        assert attempts <= 8, "refunding every retry bypassed the real outer iteration budget"
        setattr(state._retry, restart_flag, True)
        if restart_flag == "restart_with_redirected_messages":
            instance._pending_redirect = f"correction-{attempts}"
        return None

    with patch("agent.conversation_loop._run_api_retry_loop", side_effect=interrupted_attempt):
        result = agent.run_conversation("finish the work")
    assert attempts == 3, "the per-turn retry cap must also bound refunded restarts"
    assert not result["completed"]
    if restart_flag == "restart_with_redirected_messages":
        assert result["pending_steer"] == "correction-3", "the unapplied user correction must survive the cap"
    agent.client.chat.completions.create.return_value = _mock_response(content="Fresh answer", finish_reason="stop")
    second = agent.run_conversation("new request", conversation_history=result["messages"])
    assert second["completed"] and second["final_response"] == "Fresh answer"
    assert agent.client.chat.completions.create.call_count == 1


@pytest.mark.parametrize("content", ["Useful partial answer", ""])
def test_full_prompt_stops_continuations_and_leaves_a_usable_transcript(agent, content):
    agent.context_compressor.context_length = 8192
    first = _mock_response(content=content, finish_reason="length")
    first.usage = SimpleNamespace(prompt_tokens=8096, completion_tokens=32, total_tokens=8128)
    agent.client.chat.completions.create.side_effect = [first, _mock_response(content="Unexpected continuation", finish_reason="stop")]
    result = agent.run_conversation("explain the project")
    assert agent.client.chat.completions.create.call_count == 1
    assert not result["completed"] and result["partial"]
    assert "context window" in result["final_response"].lower()
    if content:
        assert content in result["final_response"]
    assert not any(m.get("_length_continuation_nudge") or m.get("_length_continuation_fragment") for m in result["messages"])
    assert not any(m.get("role") == "assistant" and not (m.get("content") or m.get("api_content") or m.get("tool_calls")) for m in result["messages"])
    agent.client.chat.completions.create.side_effect = [_mock_response(content="Fresh answer", finish_reason="stop")]
    second = agent.run_conversation("new request", conversation_history=result["messages"])
    assert second["completed"] and second["final_response"] == "Fresh answer"


def test_unknown_usage_and_ample_headroom_keep_normal_continuation(agent):
    agent.context_compressor.context_length = 8192
    for usage in (None, SimpleNamespace(prompt_tokens=500, completion_tokens=32, total_tokens=532)):
        first = _mock_response(content="Opening fragment", finish_reason="length")
        first.usage = usage
        agent.client.chat.completions.create.reset_mock()
        agent.client.chat.completions.create.side_effect = [first, _mock_response(content="completed answer", finish_reason="stop")]
        result = agent.run_conversation("explain the project")
        assert result["completed"]
        assert agent.client.chat.completions.create.call_count == 2


@pytest.mark.parametrize("prior_fragment", [False, True])
def test_partial_stream_context_overflow_uses_terminal_compression_contract(agent, prior_fragment):
    from agent.chat_completion_helpers import ProviderStreamError, _StreamingCall

    stream = object.__new__(_StreamingCall)
    stream.agent = agent
    stream.result = {"error": ProviderStreamError(
        status_code=400,
        body={"error": {"code": "context_length_exceeded", "message": "Maximum context length exceeded"}},
        raw_text="context_length_exceeded",
    )}
    partial = "Text already delivered before the provider rejected its context"
    agent._current_streamed_assistant_text = partial
    stub = stream._partial_stream_stub()
    responses = [_mock_response(content="Earlier continuation fragment", finish_reason="length")] if prior_fragment else []
    agent.client.chat.completions.create.side_effect = [*responses, stub, _mock_response(content="Unexpected continuation", finish_reason="stop")]
    with patch.object(agent, "_persist_session", side_effect=type(agent)._persist_session.__get__(agent)):
        result = agent.run_conversation("continue the analysis")
    assert agent.client.chat.completions.create.call_count == 1 + int(prior_fragment)
    assert result["failed"] and not result["completed"]
    assert result["compression_exhausted"] is True
    assert partial in result["final_response"]
    if prior_fragment:
        assert "Earlier continuation fragment" in result["final_response"]
    assert any(partial in str(m.get("content", "")) for m in result["messages"] if m.get("role") == "assistant")
    durable = agent._session_db.get_messages(agent.session_id)
    assert any(partial in str(m.get("content", "")) for m in durable if m.get("role") == "assistant")
    assert not any(m.get("_length_continuation_nudge") or m.get("_length_continuation_fragment") for m in result["messages"])
    assert not any(m.get("tool_calls") for m in durable)
    assert not any(m.get("role") == "assistant" and not (m.get("content") or m.get("api_content") or m.get("tool_calls")) for m in result["messages"])


@pytest.mark.parametrize("status, code, message", [
    (413, "payload_too_large", "Request body too large"),
    (502, "upstream_error", "Connection reset by upstream"),
])
def test_other_partial_stream_failures_keep_their_existing_recovery(agent, status, code, message):
    from agent.chat_completion_helpers import ProviderStreamError, _StreamingCall

    stream = object.__new__(_StreamingCall)
    stream.agent = agent
    stream.result = {"error": ProviderStreamError(status_code=status,
        body={"error": {"code": code, "message": message}}, raw_text=message)}
    agent._current_streamed_assistant_text = "Delivered partial text"
    stub = stream._partial_stream_stub()
    assert not getattr(stub, "_overflow_terminal", False)
    agent.client.chat.completions.create.side_effect = [stub, _mock_response(content="Recovered answer", finish_reason="stop")]
    result = agent.run_conversation("continue the analysis")
    assert result["completed"] and agent.client.chat.completions.create.call_count == 2
