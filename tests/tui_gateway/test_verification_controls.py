"""Desktop evidence uses its real session workspace and durable profile identity."""
import importlib
import json
import subprocess
import threading

import pytest


@pytest.fixture
def context(tmp_path, monkeypatch):
    from zeus_constants import set_zeus_home_override, reset_zeus_home_override
    home = tmp_path / "profile"
    home.mkdir()
    monkeypatch.setenv("ZEUS_HOME", str(home))
    root = tmp_path / "project"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / "package.json").write_text(json.dumps({"scripts": {"test": "vitest"}}), encoding="utf-8")
    server = importlib.import_module("tui_gateway.server")
    monkeypatch.setattr(server, "_sessions", {"runtime": {
        "session_key": "durable", "cwd": str(root), "explicit_cwd": True, "profile_home": home,
    }})
    monkeypatch.setattr(server, "_effective_terminal_backend", lambda: "local")
    token = set_zeus_home_override(home)
    yield server, root
    reset_zeus_home_override(token)


def test_live_read_uses_stored_session_and_workspace_and_baseline_is_real(context, tmp_path):
    server, root = context
    from agent.verification_evidence import record_terminal_result, verification_status
    from agent.workspace_identity import capture_workspace
    record_terminal_result(command="npm test", cwd=root, session_id="durable", exit_code=0,
                           workspace_before=capture_workspace(root))
    params = {"session_id": "runtime", "session_key": "spoofed", "cwd": str(tmp_path)}
    response = server._methods["verification.status"](1, params)
    report = response["result"]["verification"]
    assert report["status"] == "passed"
    assert report["session_id"] == "durable"
    assert report["root"] == str(root.resolve())
    saved = server._methods["verification.baseline.capture"](2, params)["result"]["baseline"]
    assert verification_status(session_id="durable", cwd=root)["baseline"]["id"] == saved["id"]
    assert server._methods["verification.baseline.clear"](3, params)["result"]["cleared"]
    assert verification_status(session_id="durable", cwd=root)["baseline"] is None


def test_mutation_requires_live_session_and_local_workspace(context, monkeypatch):
    server, root = context
    method = server._methods["verification.baseline.capture"]
    assert "error" in method(1, {"session_id": "missing", "cwd": str(root)})
    monkeypatch.setattr(server, "_effective_terminal_backend", lambda: "ssh")
    assert "error" in method(2, {"session_id": "runtime"})
    report = server._methods["verification.status"](3, {"session_id": "runtime"})["result"]["verification"]
    assert report["status"] == "unknown"
    assert report["workspace"]["status"] == "unavailable"


def test_experience_slash_reads_the_live_project_and_rejects_host_path_spoofing(context, tmp_path, monkeypatch):
    server, root = context
    from agent.verification_evidence import begin_verify_run, record_verify_run
    record_verify_run(root=root, session_id="durable", ok=False, output="Recorded project failure",
                      workspace_before=begin_verify_run(root=root, session_id="durable"))
    reply = server._methods["experience.command"](1, {"session_id": "runtime", "cwd": str(tmp_path), "command": "list"})
    assert "Recorded project failure" in reply["result"]["output"]
    catalog = server._methods["commands.catalog"](4, {})["result"]
    assert catalog["commands"]["/experience"]["desktop"] is None
    text = server._methods["slash.exec"](5, {"session_id": "runtime", "command": "/experience list"})
    assert "Recorded project failure" in text["result"]["output"]
    assert "error" in server._methods["experience.command"](2, {"session_id": "missing", "cwd": str(root)})
    monkeypatch.setattr(server, "_effective_terminal_backend", lambda: "ssh")
    rejected = server._methods["experience.command"](3, {"session_id": "runtime"})
    assert "error" in rejected


@pytest.mark.parametrize("method", ["verification.status", "verification.baseline.capture",
                                   "verification.baseline.clear", "experience.command", "session.control.read", "session.control",
                                   "hermes.migration.scan", "hermes.migration.import"])
def test_slow_evidence_does_not_block_the_rpc_reader(context, monkeypatch, method):
    server, _ = context
    entered, release, replied = threading.Event(), threading.Event(), threading.Event()
    responses = []

    class Transport:
        def write(self, response):
            responses.append(response)
            replied.set()
            return True

    def inspect(rid, params):
        entered.set()
        release.wait(2)
        return server._ok(rid, {"observed": True})

    monkeypatch.setitem(server._methods, method, inspect)
    monkeypatch.setitem(server._methods, "test.reader.ping", lambda rid, params: server._ok(rid, {"pong": True}))
    transport = Transport()
    try:
        result = server.dispatch({"id": 1, "method": method, "params": {}}, transport)
        assert result is None, "slow inspection must yield the reader to the next incoming command"
        assert entered.wait(2)
        assert server.dispatch({"id": 2, "method": "test.reader.ping", "params": {}}, transport)["result"]["pong"]
        assert not replied.is_set()
    finally:
        release.set()
    assert replied.wait(2)
    assert responses[0]["result"]["observed"]
