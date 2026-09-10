"""Resolved batch answers must survive the real tool-result pruning pass."""
import json

import pytest

from agent.context_compressor import ContextCompressor, _PRUNE_MIN_CHARS


@pytest.mark.parametrize("entries, expected", [
    ([{"user_response": "Friday"}, {"user_response": ["lint", "tests"]}], ["Friday", "lint", "tests"]),
    ([{"user_response": "Friday"}, {"user_response": "[user did not respond within 15m]"}], ["Friday"]),
    ([None, {"user_response": {"diagnostic": "internal"}}, {"user_response": "Friday"}], ["Friday"]),
])
def test_batch_answers_survive_repeated_pruning_without_mutating_original(entries, expected):
    compressor = ContextCompressor(model="test/model", quiet_mode=True)
    payload = json.dumps({"responses": entries, "question_metadata": "x" * 600})
    messages = [
        {"role": "user", "content": "Choose the delivery plan"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "clarify-1", "type": "function",
         "function": {"name": "clarify", "arguments": '{"questions":[]}'}}]},
        {"role": "tool", "tool_call_id": "clarify-1", "content": payload},
        {"role": "assistant", "content": "I will follow those choices."},
    ]
    pruned, count = compressor._prune_old_tool_results(messages, protect_tail_count=1)
    assert count == 1
    summary = pruned[2]["content"]
    assert summary.startswith("[clarify] user responded: ")
    assert json.loads(summary.split(": ", 1)[1]) == expected
    assert "diagnostic" not in summary and "did not respond" not in summary
    assert len(summary) < _PRUNE_MIN_CHARS
    again, count = compressor._prune_old_tool_results(pruned, protect_tail_count=1)
    assert again == pruned and count == 0
    assert messages[2]["content"] == payload


def test_unanswered_batch_does_not_invent_a_user_answer():
    compressor = ContextCompressor(model="test/model", quiet_mode=True)
    messages = [
        {"role": "assistant", "content": "", "tool_calls": [{"id": "c", "type": "function",
         "function": {"name": "clarify", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "c", "content": json.dumps({
            "responses": [{"user_response": "[user did not respond within 15m]"}], "metadata": "x" * 600,
        })},
    ]
    pruned, _ = compressor._prune_old_tool_results(messages, protect_tail_count=0)
    assert pruned[1]["content"] == "[clarify] asked user a question"
