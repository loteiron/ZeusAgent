"""Messaging inspection is private, profile scoped and never starts an agent turn."""
import json
import subprocess
from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_only_the_explicit_private_owner_can_inspect_profile_experience(tmp_path, monkeypatch):
    from gateway.config import GatewayConfig, Platform, PlatformConfig
    from gateway.platforms.event import MessageEvent, MessageType
    from gateway.run import GatewayRunner
    from gateway.session import SessionSource
    from agent.verification_evidence import begin_verify_run, record_verify_run

    profile = tmp_path / "profile"
    profile.mkdir()
    monkeypatch.setenv("ZEUS_HOME", str(profile))
    root = tmp_path / "project"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (profile / "config.yaml").write_text(json.dumps({"terminal": {"cwd": str(root), "backend": "local"}}), encoding="utf-8")
    record_verify_run(root=root, session_id="first", ok=False, output="Private project diagnostic",
                     workspace_before=begin_verify_run(root=root, session_id="first"))
    platform_cfg = PlatformConfig(enabled=True, extra={"allow_from": ["owner"]})
    runner = object.__new__(GatewayRunner)
    runner.config = GatewayConfig(platforms={Platform.TELEGRAM: platform_cfg})
    runner._adapter_for_source = lambda source: SimpleNamespace(config=platform_cfg)
    runner._resolve_profile_home_for_source = lambda source: profile

    def event(user="owner", chat_type="dm", text="/experience"):
        return MessageEvent(text=text, message_type=MessageType.COMMAND,
                            source=SessionSource(platform=Platform.TELEGRAM, user_id=user, chat_id="chat", chat_type=chat_type))

    assert "Private project diagnostic" in await runner._handle_experience_command(event())
    assert "Private project diagnostic" not in await runner._handle_experience_command(event(user="other"))
    assert "Private project diagnostic" not in await runner._handle_experience_command(event(chat_type="group"))
    assert "Usage:" in await runner._handle_experience_command(event(text="/experience forget anything"))
    assert "Usage:" in await runner._handle_experience_command(event(text="/experience list --root /"))
    runner.config.multiplex_profiles = True
    runner._adapter_for_source = lambda source: SimpleNamespace(config=None)
    assert "Private project diagnostic" not in await runner._handle_experience_command(event())
