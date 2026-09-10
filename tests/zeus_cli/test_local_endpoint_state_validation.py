"""A corrupt runtime record must not crash or become a provider endpoint."""

import json

import pytest

from zeus_cli.local_runtime import endpoint
from zeus_cli.local_runtime.supervisor import state_path


@pytest.mark.parametrize("payload", [
    b"\xff", b'{"base_url":',
    None, [], 7, "not-a-record",
    {"base_url": "http://127.0.0.1:18434/v1", "pid": "invalid"},
    {"base_url": "http://127.0.0.1:18434/v1", "pid": [123]},
    {"base_url": ["http://127.0.0.1:18434/v1"], "pid": 123},
    {"base_url": "http://127.0.0.1:18434/v1", "pid": 123, "api_key": {"unexpected": "object"}},
])
def test_malformed_state_is_ignored_without_mutation(payload, monkeypatch):
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    original = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
    path.write_bytes(original)
    # The process can be alive while a truncated/miswritten record is unusable.
    monkeypatch.setattr(endpoint, "_pid_alive", lambda pid: True)
    monkeypatch.setattr("zeus_cli.local_runtime.detect.DEFAULT_PROBE_PORTS", ())
    assert endpoint.resolve_llamacpp_endpoint(config={}, wait_for_boot_s=0) is None
    assert path.read_bytes() == original


@pytest.mark.parametrize("pid", [123, "123"])
def test_valid_state_preserves_endpoint_and_ownership_probe(pid, monkeypatch):
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    state = {"base_url": "http://127.0.0.1:18434/v1", "pid": pid, "api_key": "test-only"}
    path.write_text(json.dumps(state), encoding="utf-8")
    seen = []
    monkeypatch.setattr(endpoint, "_pid_alive", lambda value: seen.append(value) or True)
    assert endpoint.resolve_llamacpp_endpoint(config={}, wait_for_boot_s=0) == {
        "base_url": state["base_url"], "api_key": state["api_key"],
    }
    assert seen == [123]
