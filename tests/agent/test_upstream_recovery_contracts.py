"""Runtime regressions identified against the pinned 2026-09-10 upstream core."""
from __future__ import annotations

import base64
from copy import deepcopy
import io
import math
import time

import httpx
from openai import AuthenticationError, BadRequestError
import pytest


@pytest.fixture
def agent(tmp_path, monkeypatch):
    monkeypatch.setenv("ZEUS_HOME", str(tmp_path))
    (tmp_path / "config.yaml").write_text("{}\n", encoding="utf-8")
    from run_agent import AIAgent
    from zeus_state import SessionDB

    db = SessionDB(db_path=tmp_path / "sessions.db")
    instance = AIAgent(
        session_db=db, model="test-model", provider="openai-compat",
        api_key="test", base_url="http://127.0.0.1:1/v1", quiet_mode=True,
        skip_context_files=True, skip_memory=True, run_budget_seconds=900,
    )
    yield instance
    db.close()


def tool_round(call_id, content):
    return [
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": call_id, "type": "function", "function": {"name": "read_file", "arguments": "{}"}},
        ]},
        {"role": "tool", "tool_call_id": call_id, "content": content},
    ]


@pytest.mark.parametrize("content", ["read result", [{"type": "text", "text": "read result"}]])
def test_run_budget_notice_is_durable_before_tool_progress_is_reported(agent, content):
    from agent.conversation_loop import RUN_BUDGET_WRAPUP_NOTICE
    from agent.tool_executor import _flush_session_db_after_tool_progress
    from agent.turn_iteration_prep import prepare_iteration

    agent._run_budget_started_at = time.time() - 800
    messages = [{"role": "user", "content": "finish the work"}, *tool_round("first", content)]
    assert _flush_session_db_after_tool_progress(agent, messages, stage="test")
    durable = agent._session_db.get_messages(agent.session_id)
    assert RUN_BUDGET_WRAPUP_NOTICE in str(durable[-1]["content"])
    snapshot = deepcopy(messages)
    prepare_iteration(agent, messages=messages, api_call_count=1)
    assert messages == snapshot
    assert agent._session_db.get_messages(agent.session_id) == durable


def test_crossing_run_budget_after_checkpoint_preserves_cached_and_replayed_prefix(agent):
    from agent.conversation_loop import RUN_BUDGET_WRAPUP_NOTICE
    from agent.tool_executor import _flush_session_db_after_tool_progress
    from agent.turn_iteration_prep import prepare_iteration

    agent._run_budget_started_at = time.time() - 100
    messages = [{"role": "user", "content": "finish the work"}, *tool_round("first", "old result")]
    assert _flush_session_db_after_tool_progress(agent, messages, stage="first")
    durable = agent._session_db.get_messages(agent.session_id)
    snapshot = deepcopy(messages)
    agent._run_budget_started_at = time.time() - 800
    prepare_iteration(agent, messages=messages, api_call_count=1)
    assert messages == snapshot, "a cached, persisted result cannot receive a late budget notice"
    assert agent._run_budget_wrapup_injected is False
    messages.extend(tool_round("second", "new result"))
    assert _flush_session_db_after_tool_progress(agent, messages, stage="second")
    replay = agent._session_db.get_messages(agent.session_id)
    assert replay[:len(durable)] == durable
    assert RUN_BUDGET_WRAPUP_NOTICE in replay[-1]["content"]
    assert sum(RUN_BUDGET_WRAPUP_NOTICE in str(row["content"]) for row in replay) == 1


def test_nonretryable_auth_failure_retains_classifier_verdict_for_desktop_recovery(agent):
    from agent.error_classifier import classify_api_error
    from agent.error_surface import build_error_surface_from_result
    from agent.turn_recovery import nonretryable_client_error_result

    error = AuthenticationError(
        "The authentication token was rejected",
        response=httpx.Response(401, request=httpx.Request("POST", "https://example.invalid/v1/responses")),
        body={"error": {"message": "The authentication token was rejected"}},
    )
    classified = classify_api_error(error, provider="openai-codex", model="test-model")
    assert classified.is_auth and not classified.retryable
    messages = [{"role": "user", "content": "resume the work"}]
    result = nonretryable_client_error_result(
        agent, error, classified, status_code=401, api_kwargs=None,
        api_messages=messages, messages=messages, conversation_history=[],
        api_call_count=1, approx_tokens=20, provider="openai-codex",
        base_url="https://example.invalid/v1", model="test-model",
    )
    descriptor = build_error_surface_from_result(result, provider="openai-codex", model="test-model")
    assert descriptor["layer"] == "auth"
    assert descriptor["retryable"] is False
    assert result["failure_reason"] == classified.reason.value
    assert result["failure_retryable"] is classified.retryable


def test_codex_patch_budget_error_shrinks_a_real_image_before_retrying(agent):
    from PIL import Image
    from agent.error_classifier import FailoverReason, classify_api_error
    from agent.turn_recovery import recover_after_classification
    from agent.turn_retry_state import TurnRetryState

    image = Image.new("RGB", (6000, 6000), (31, 63, 95))
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    image.close()
    original = "data:image/png;base64," + base64.b64encode(stream.getvalue()).decode("ascii")
    error = BadRequestError(
        "Image has 35344 patches after processing, exceeding the limit of 30000",
        response=httpx.Response(400, request=httpx.Request("POST", "https://example.invalid/v1/responses")),
        body=None,
    )
    classified = classify_api_error(error, provider="openai-codex", model="test-model")
    assert classified.reason is FailoverReason.image_too_large
    messages = [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": original}}]}]
    retry = TurnRetryState()
    recovered, pooled = recover_after_classification(
        agent, error, classified, retry, status_code=400, error_context={},
        messages=messages, api_messages=messages,
    )
    assert recovered and not pooled
    assert retry.image_shrink_retry_attempted
    resized = messages[0]["content"][0]["image_url"]["url"]
    assert resized != original
    with Image.open(io.BytesIO(base64.b64decode(resized.split(",", 1)[1]))) as shrunk:
        assert math.ceil(shrunk.width / 32) * math.ceil(shrunk.height / 32) <= 30000
    assert recover_after_classification(
        agent, error, classified, retry, status_code=400, error_context={},
        messages=messages, api_messages=messages,
    ) == (False, False), "a repeated rejection must not create an unbounded image retry"
