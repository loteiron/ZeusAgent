"""The cache diagnostic records SDK requests without changing their prefix."""
import copy
import json
from pathlib import Path
import runpy
import shutil
import sys

import anthropic
from anthropic.resources.messages import Messages
import httpx
from openai import OpenAI
from openai.resources.chat.completions import Completions
import pytest


@pytest.mark.parametrize("wire", ["native", "chat"])
def test_cache_probe_preserves_and_records_request_prefix(tmp_path, monkeypatch, wire):
    import agent.prompt_caching as caching
    monkeypatch.setattr(Messages, "stream", Messages.stream)
    monkeypatch.setattr(Completions, "create", Completions.create)
    monkeypatch.setattr(caching, "effective_cache_ttl", caching.effective_cache_ttl)
    out = tmp_path / "calls.jsonl"
    monkeypatch.setattr(sys, "argv", [
        "cache-probe", "--repo", str(Path(__file__).resolve().parents[1]),
        "--provider", "anthropic" if wire == "native" else "openrouter",
        "--workers", "0", "--out", str(out), "--api-key", "unit-test-only",
    ])
    probe = runpy.run_module("evals.postmortem.live_ab.cache_concurrency_probe")
    requests = []

    def transport(request):
        requests.append(json.loads(request.content))
        if wire == "chat":
            return httpx.Response(200, json={
                "id": "chat-test", "object": "chat.completion", "created": 1, "model": "test-model",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 8, "completion_tokens": 1, "total_tokens": 9,
                          "prompt_tokens_details": {"cached_tokens": 4}},
            })
        events = [
            ("message_start", {"type": "message_start", "message": {
                "id": "msg-test", "type": "message", "role": "assistant", "model": "test-model",
                "content": [], "stop_reason": None, "stop_sequence": None,
                "usage": {"input_tokens": 4, "output_tokens": 1, "cache_read_input_tokens": 4,
                          "cache_creation_input_tokens": 0}}}),
            ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                               "usage": {"output_tokens": 1}}),
            ("message_stop", {"type": "message_stop"}),
        ]
        body = ''.join(f'event: {kind}\ndata: {json.dumps(data)}\n\n' for kind, data in events)
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream", "request-id": "request-test"})

    messages = [{"role": "user", "content": "[probe-session 7] hello"}]
    original = copy.deepcopy(messages)
    try:
        with httpx.Client(transport=httpx.MockTransport(transport)) as http:
            client = (anthropic.Anthropic(api_key="unit-test-only", http_client=http) if wire == "native"
                      else OpenAI(api_key="unit-test-only", http_client=http))
            for turn in range(2):
                if turn:
                    messages.extend([{"role": "assistant", "content": "ok"}, {"role": "user", "content": "next"}])
                if wire == "native":
                    with client.messages.stream(model="test-model", max_tokens=8, system="Stable system", messages=messages) as stream:
                        list(stream)
                        stream.get_final_message()
                else:
                    client.chat.completions.create(model="test-model", messages=[{"role": "system", "content": "Stable system"}, *messages])
        records = [json.loads(line) for line in out.read_text().splitlines()]
        assert len(requests) == len(records) == 2
        assert all(r["worker"] == 7 and r["cache_read"] > 0 for r in records)
        assert records[0]["system_sha"] == records[1]["system_sha"]
        assert records[0]["tools_sha"] == records[1]["tools_sha"]
        assert records[0]["msg_shas"] == records[1]["msg_shas"][:1]
        assert records[1]["call"] > records[0]["call"]
        assert messages[:1] == original
    finally:
        shutil.rmtree(probe["WORKDIR"])
