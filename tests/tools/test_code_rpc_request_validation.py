"""Malformed RPC input must not stop service or repeat a side effect."""

import json
import socket
import subprocess
import threading
import time

import pytest

from tools import code_execution_rpc as rpc


@pytest.mark.parametrize(
    "invalid",
    [None, [], 7, "text", {"tool": []}, {"tool": {}},
     {"tool": "terminal", "args": []}, {"tool": "terminal", "args": "text"},
     {"tool": "\ud800"}],
)
def test_socket_rejects_invalid_input_and_serves_next_request(invalid):
    calls, errors, call_log, count = [], [], [], [0]
    stop = threading.Event()
    token = "test-rpc-validation-token"

    def dispatch(name, args):
        calls.append((name, args))
        return json.dumps({"output": "accepted"})

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)

        def serve():
            try:
                rpc._rpc_server_loop(
                    listener, "validation", call_log, count, 1,
                    frozenset({"terminal"}), stop, token, dispatch=dispatch,
                )
            except Exception as exc:
                errors.append(exc)

        worker = threading.Thread(target=serve, daemon=True)
        worker.start()
        try:
            with socket.create_connection(listener.getsockname(), timeout=3) as client:
                with client.makefile("rwb") as stream:
                    bad = {**invalid, "token": token} if isinstance(invalid, dict) else invalid
                    unauthorized = [{"token": value, "tool": "terminal", "args": {}}
                                    for value in ("wrong", None, 42, [], {}, "\ud800")]
                    for request in (bad, *unauthorized):
                        stream.write(json.dumps(request).encode() + b"\n")
                        stream.flush()
                        reply = stream.readline()
                        assert reply, f"RPC closed after malformed input: {errors}"
                        assert "error" in json.loads(reply)
                        assert count == [0] and calls == []
                    valid = {"token": token, "tool": "terminal", "args": {"command": "echo ok"}}
                    stream.write(json.dumps(valid).encode() + b"\n")
                    stream.flush()
                    assert json.loads(stream.readline()) == {"output": "accepted"}
        finally:
            stop.set()
            worker.join(timeout=3)
        assert not worker.is_alive() and errors == []
        assert calls == [("terminal", {"command": "echo ok"})]
        assert count == [1] and len(call_log) == 1


@pytest.mark.linux_only
@pytest.mark.parametrize("invalid_seq", [None, "1", 1.5, -1, True, [], {}])
@pytest.mark.parametrize("response", ["accepted", "\ud800"])
def test_remote_invalid_sequence_cannot_dispatch_or_starve_next_request(
    tmp_path, monkeypatch, invalid_seq, response
):
    calls, call_log, count = [], [], [0]
    stop = threading.Event()
    token = "test-rpc-validation-token"
    bad = tmp_path / "req_000001"
    good = tmp_path / "req_000002"
    bad.write_text(json.dumps({"token": token, "seq": invalid_seq,
                               "tool": "terminal", "args": {"command": "bad"}}))
    good.write_text(json.dumps({"token": token, "seq": 2,
                                "tool": "terminal", "args": {"command": "good"}}))

    class LocalFiles:
        def execute(self, command, *, cwd, timeout):
            result = subprocess.run(command, shell=True, cwd=cwd, timeout=timeout,
                                    text=True, capture_output=True)
            return {"output": result.stdout, "exit_code": result.returncode}

    def dispatch(name, args):
        calls.append((name, args))
        return json.dumps({"output": response}, ensure_ascii=False)

    monkeypatch.setattr(rpc, "_default_dispatch", lambda task_id: dispatch)
    worker = threading.Thread(
        target=rpc._rpc_poll_loop,
        args=(LocalFiles(), str(tmp_path), "validation", call_log, count, 20,
              frozenset({"terminal"}), stop, token), daemon=True,
    )
    worker.start()
    try:
        deadline = time.monotonic() + 3
        while (bad.exists() or good.exists()) and time.monotonic() < deadline:
            stop.wait(0.02)
    finally:
        stop.set()
        worker.join(timeout=3)
    assert not worker.is_alive()
    assert not bad.exists() and not good.exists()
    assert calls == [("terminal", {"command": "good"})]
    assert count == [1] and len(call_log) == 1
    assert json.loads((tmp_path / "res_000002").read_text()) == {"output": response}
