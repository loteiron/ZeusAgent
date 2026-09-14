"""Live Telegram command authorization and session isolation."""
from unittest.mock import Mock

import pytest

from agent.autonomy import clear_mode, is_enabled
from gateway.config import GatewayConfig, Platform, PlatformConfig
from gateway.platforms.event import MessageEvent
from gateway.run import GatewayRunner
from gateway.session import SessionSource


@pytest.fixture
def runner(tmp_path, monkeypatch):
    monkeypatch.setenv("ZEUS_HOME", str(tmp_path))
    r = object.__new__(GatewayRunner)
    r.config = GatewayConfig(platforms={Platform.TELEGRAM: PlatformConfig(
        enabled=True, token="test", extra={"allow_from": ["owner"]})})
    r.session_store = None
    r.adapters = {}
    r._running_agents = {}
    yield r
    clear_mode(r._session_key_for_source(event().source))


def event(text="/autonom", user="owner", chat_type="dm", internal=False):
    return MessageEvent(text=text, internal=internal, source=SessionSource(
        platform=Platform.TELEGRAM, user_id=user, chat_id="chat", chat_type=chat_type))


@pytest.mark.asyncio
async def test_owner_can_enable_status_and_disable_while_busy(runner):
    from zeus_cli.commands import resolve_command
    message = event()
    key = runner._session_key_for_source(message.source)
    result = await runner._dispatch_busy_slash_command(message, resolve_command("autonom"), key, message.source)
    assert "ON" in result
    assert is_enabled(key)
    assert runner._effective_busy_input_mode(message.source) == "steer"
    assert "ON" in await runner._handle_autonom_command(event("/autonom status"))
    assert "OFF" in await runner._handle_autonom_command(event("/autonom off"))
    assert not is_enabled(key)


@pytest.mark.asyncio
@pytest.mark.parametrize("message", [event(user="stranger"), event(chat_type="group"), event(internal=True)])
async def test_untrusted_sources_cannot_enable_autonomy(runner, message):
    result = await runner._handle_autonom_command(message)
    assert "requires" in result
    assert not is_enabled(runner._session_key_for_source(message.source))
