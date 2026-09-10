"""Telegram slash intent must never become an accidental busy-turn steering message."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from gateway.config import GatewayConfig, Platform, PlatformConfig
from gateway.platforms.base import BasePlatformAdapter
from gateway.platforms.event import MessageEvent
from gateway.session import SessionSource, build_session_key


class _Adapter(BasePlatformAdapter):
    async def connect(self, *, is_reconnect=False):
        return True

    async def disconnect(self):
        pass

    async def send(self, chat_id, text, **kwargs):
        pass

    async def get_chat_info(self, chat_id):
        return {}


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["/mistyped_zeus_command", "/check_loop@Zeus_Bot", "/broken_lookup"])
async def test_busy_slash_keeps_running_agent_and_pending_human_message_intact(text, monkeypatch):
    from gateway.run import GatewayRunner

    source = SessionSource(platform=Platform.TELEGRAM, chat_id="room", user_id="owner", chat_type="dm")
    key = build_session_key(source)
    adapter = _Adapter(PlatformConfig(enabled=True, token="test"), Platform.TELEGRAM)
    adapter._busy_text_mode = "interrupt"
    adapter._send_with_retry = AsyncMock()
    runner = object.__new__(GatewayRunner)
    runner.config = GatewayConfig(quick_commands={"check_loop": {"type": "alias", "target": "/loop status"}})
    runner.adapters = {Platform.TELEGRAM: adapter}
    runner._is_user_authorized = lambda _source: True
    runner._check_slash_access = lambda _source, _command: None
    runner._draining = False
    runner._effective_busy_input_mode = lambda _source: "steer"
    runner._effective_busy_text_mode = lambda _source: "interrupt"
    runner._route_plaintext_approval_while_busy = AsyncMock(return_value=False)
    runner._peek_session_state = lambda _key: SimpleNamespace(turn=SimpleNamespace(agent=Mock()))
    runner._resolve_busy_steer_or_redirect = AsyncMock(side_effect=AssertionError("A slash command reached model steering"))
    runner._handle_loop_command = AsyncMock(return_value="Loop active: check the deployment")
    runner._send_busy_reply = AsyncMock()
    if text == "/broken_lookup":
        monkeypatch.setattr("zeus_cli.plugins.get_plugin_command_handler",
                            Mock(side_effect=RuntimeError("plugin index unavailable")))
    adapter._busy_session_handler = runner._handle_active_session_busy_message

    async def command_handler(event):
        handled, reply = await runner._hm_busy_slash_or_photo(event, source, key)
        assert handled
        return reply

    adapter._message_handler = command_handler
    guard = asyncio.Event()
    adapter._active_sessions[key] = guard
    queued = MessageEvent(text="keep this human request", source=source)
    adapter._pending_messages[key] = queued
    await adapter.handle_message(MessageEvent(text=text, source=source))

    runner._resolve_busy_steer_or_redirect.assert_not_awaited()
    assert adapter._pending_messages[key] is queued
    assert queued.text == "keep this human request"
    assert adapter._active_sessions[key] is guard and not guard.is_set()
    replies = [str(call.args) for call in runner._send_busy_reply.await_args_list + adapter._send_with_retry.await_args_list]
    assert any("Unknown command" in reply or "Loop active" in reply or "lookup is temporarily unavailable" in reply
               for reply in replies)
    if text.startswith("/check_loop"):
        runner._handle_loop_command.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("chat_type", ["private", "group"])
@pytest.mark.parametrize("text,accepted", [("/stop@another_bot", False), ("/status@ZEUS_BOT", True), ("/status", True)])
async def test_only_commands_addressed_to_this_bot_control_zeus(chat_type, text, accepted):
    from plugins.platforms.telegram.adapter import TelegramAdapter

    adapter = object.__new__(TelegramAdapter)
    adapter.platform = Platform.TELEGRAM
    adapter.config = PlatformConfig(enabled=True, token="test", extra={
        "require_mention": False, "exclusive_bot_mentions": False,
        "allowed_chats": [], "allowed_topics": [],
    })
    adapter._bot = SimpleNamespace(id=999, username="Zeus_Bot")
    adapter._bot_username_observed = None
    adapter._observe_bot_identity_from_message = lambda _message: None
    adapter._is_user_authorized_from_message = lambda _message: True
    adapter._ensure_forum_commands = AsyncMock()
    adapter._build_triggered_event = AsyncMock(return_value=MessageEvent(text=text))
    adapter.handle_message = AsyncMock()
    message = SimpleNamespace(
        text=text, entities=[], caption=None, caption_entities=[],
        message_thread_id=None, is_topic_message=False, reply_to_message=None,
        from_user=SimpleNamespace(id=123), chat=SimpleNamespace(id=123, type=chat_type),
    )
    await adapter._handle_command(SimpleNamespace(effective_message=message), None)
    if accepted:
        adapter.handle_message.assert_awaited_once()
    else:
        adapter.handle_message.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["/tmp/project/file.py explain this", "/home/user@host/source.py", "Explain /goal pause without running it"])
async def test_paths_and_command_mentions_remain_conversational(text):
    from gateway.run import GatewayRunner

    runner = object.__new__(GatewayRunner)
    event = MessageEvent(text=text)
    handled, reply = await runner._hm_busy_slash_or_photo(event, event.source, "session")
    assert handled is False and reply is None
    assert event.text == text


@pytest.mark.asyncio
async def test_busy_alias_cycles_and_target_authorization_fail_without_dispatch():
    from gateway.run import GatewayRunner

    runner = object.__new__(GatewayRunner)
    runner.config = GatewayConfig(quick_commands={
        "first": {"type": "alias", "target": "/second"},
        "second": {"type": "alias", "target": "/first"},
        "private": {"type": "alias", "target": "/loop pause"},
    })
    runner._check_slash_access = lambda _source, command: "Access denied" if command == "loop" else None
    runner._handle_loop_command = AsyncMock()
    for text, message in [("/first", "cycle"), ("/private", "Access denied")]:
        event = MessageEvent(text=text)
        handled, reply = await runner._hm_busy_slash_or_photo(event, event.source, "session")
        assert handled and message in reply
    runner._handle_loop_command.assert_not_awaited()
