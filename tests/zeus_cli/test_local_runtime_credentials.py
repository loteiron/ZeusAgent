"""Managed local credentials must stay private on disk and out of logs."""

import json
import stat
from types import SimpleNamespace

import pytest

from zeus_cli.local_runtime import supervisor as runtime


@pytest.mark.linux_only
@pytest.mark.parametrize("existing", [None, b"existing-test-key-123456789", b"\xff"])
def test_key_and_state_are_private_and_valid_key_survives_restart(tmp_path, monkeypatch, existing):
    monkeypatch.setenv("ZEUS_HOME", str(tmp_path))
    key_path = runtime.runtimes_root() / ".api_key"
    if existing is not None:
        key_path.parent.mkdir(parents=True)
        key_path.write_bytes(existing)
        key_path.chmod(0o644)
    sup = runtime.LlamaServerSupervisor(tmp_path / "install", tmp_path / "models", port=18435)
    sup.proc = SimpleNamespace(pid=12345)
    sup._write_state()
    assert stat.S_IMODE(key_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(runtime.state_path().stat().st_mode) == 0o600
    assert json.loads(runtime.state_path().read_text())["api_key"] == sup.api_key
    second = runtime.LlamaServerSupervisor(tmp_path / "install", tmp_path / "models", port=18435)
    assert second.api_key == sup.api_key
    if existing is not None and existing.isascii():
        assert sup.api_key == existing.decode()


def test_spawn_log_does_not_disclose_key_but_child_receives_it(tmp_path, monkeypatch):
    monkeypatch.setenv("ZEUS_HOME", str(tmp_path))
    exe = tmp_path / "install" / "llama-server"
    monkeypatch.setattr(runtime, "server_binary", lambda install: exe)
    commands = []

    def spawn(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(pid=12345)

    monkeypatch.setattr(runtime.subprocess, "Popen", spawn)
    sup = runtime.LlamaServerSupervisor(exe.parent, tmp_path / "models", port=18435)
    try:
        sup._spawn()
        assert commands[0][commands[0].index("--api-key") + 1] == sup.api_key
        assert sup.api_key not in sup.log_path.read_text()
        assert str(exe) in sup.log_path.read_text()
    finally:
        if sup._log_handle:
            sup._log_handle.close()
