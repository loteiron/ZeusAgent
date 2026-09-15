"""Background learning is automatic, quiet, and cannot alter the live prompt."""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from agent.experience_review import review_signals, restore_review_cadence


def test_review_batches_meaningful_turns_and_prioritizes_explicit_corrections(monkeypatch):
    agent = SimpleNamespace(skip_memory=False, _delegate_depth=0, _memory_enabled=True,
        _user_profile_enabled=True, valid_tool_names={"skill_manage"})
    for greeting in ("selam", "merhaba!", "tamam", "teşekkürler"):
        assert review_signals(agent, greeting, "t", completed=True) == (False, False)
    assert not getattr(agent, "_learning_turns_since_review", 0)
    assert review_signals(agent, "hello", "t", completed=True) == (False, False)
    assert review_signals(agent, "Inspect the current project", "t", completed=True) == (False, False)
    assert review_signals(agent, "Explain the configuration choices", "t", completed=True) == (False, False)
    assert review_signals(agent, "Keep the working setup", "t", completed=True) == (True, True)
    assert review_signals(agent, "Bundan sonra cevapların kısa olsun", "t", completed=True) == (True, True)
    assert review_signals(agent, "Remember this preference", "t", completed=False) == (False, False)
    agent.skip_memory = True
    assert review_signals(agent, "Remember this preference", "t", completed=True) == (False, False)


def test_gateway_recreation_resumes_meaningful_turn_batch():
    agent = SimpleNamespace(_memory_enabled=True, valid_tool_names={"skill_manage"})
    restore_review_cadence(agent, [
        {"role": "user", "content": "Explain the working setup"},
        {"role": "assistant", "content": "Detailed explanation"},
        {"role": "user", "content": "hello"},
        {"role": "user", "content": "Check the configuration options"},
    ])
    assert review_signals(agent, "Keep the configuration for future tasks", "t", completed=True) == (True, True)


def test_review_worker_is_silent_but_still_executes_and_records_usage(monkeypatch):
    from agent import background_review as review

    agent = SimpleNamespace(provider="openai", memory_notifications="on",
                            _safe_print=MagicMock(), background_review_callback=MagicMock(),
                            _emit_auxiliary_failure=MagicMock())
    executed = []

    def run_fork(agent, messages, prompt, task_cfg, run, state):
        executed.append(prompt)
        state.review_messages = [
            {"role": "assistant", "tool_calls": [{"id": "learn", "type": "function", "function": {
                "name": "memory", "arguments": json.dumps({"action": "add", "target": "user",
                                                             "content": "Prefers concise replies"})}}]},
            {"role": "tool", "tool_call_id": "learn", "content": json.dumps({
                "success": True, "message": "Entry added", "target": "user"})},
        ]
        assert review.summarize_background_review_actions(state.review_messages, [])

    monkeypatch.setattr(review, "_parent_can_emit_tool_calls", lambda agent: True)
    monkeypatch.setattr(review, "_run_review_fork", run_fork)
    review._run_review_in_thread(agent, [], "review")
    assert executed == ["review"]
    agent._safe_print.assert_not_called()
    agent.background_review_callback.assert_not_called()
    agent._emit_auxiliary_failure.assert_not_called()
