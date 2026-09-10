"""Session control buttons use the authorized slash path and expire with their session."""

from contextlib import nullcontext
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from gateway.config import Platform, PlatformConfig
from gateway.platforms.event import MessageEvent
from gateway.session import SessionSource
from plugins.platforms.telegram.adapter import TelegramAdapter


@pytest.fixture(autouse=True)
def _keyboard_transport_values(monkeypatch):
    # Telegram is optional in the core test lane; retain its transport values
    # instead of the global optional-dependency MagicMock's empty iteration.
    monkeypatch.setattr("plugins.platforms.telegram.adapter.InlineKeyboardButton",
                        lambda text, callback_data: SimpleNamespace(text=text, callback_data=callback_data))
    monkeypatch.setattr("plugins.platforms.telegram.adapter.InlineKeyboardMarkup",
                        lambda rows: SimpleNamespace(inline_keyboard=rows))


def _context():
    adapter = TelegramAdapter(PlatformConfig(enabled=True, token="test-token"))
    adapter._bot = SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace(message_id=42)))
    adapter._is_callback_user_authorized = Mock(return_value=True)
    adapter.handle_message = AsyncMock()
    runner = SimpleNamespace(
        session_store=SimpleNamespace(peek_session_id=Mock(return_value="original-session")),
        _profile_scope_for_source=lambda source: nullcontext(),
        _thread_metadata_for_source=lambda source, *args: {"thread_id": source.thread_id},
        _reply_anchor_for_event=lambda event: event.message_id,
    )
    source = SessionSource(platform=Platform.TELEGRAM, chat_id="123", chat_type="forum",
                           user_id="7", thread_id="99", profile="work")
    event = MessageEvent(text="/status", source=source, message_id="41")
    entry = SimpleNamespace(session_key="route-to-original", session_id="original-session")
    return adapter, runner, event, entry


def _query(data):
    return SimpleNamespace(
        data=data, from_user=SimpleNamespace(id=7, first_name="Owner"),
        message=SimpleNamespace(chat_id=123, message_id=42, message_thread_id=99,
                                chat=SimpleNamespace(type="supergroup")),
        answer=AsyncMock(), edit_message_reply_markup=AsyncMock(),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["/status", "/stop", "/loop pause", "/loop resume"])
async def test_button_dispatch_preserves_authority_and_route(command):
    adapter, runner, event, entry = _context()
    result = await adapter.send_session_controls(runner, event, entry, "Current status")
    assert result.success
    sent = adapter._bot.send_message.await_args.kwargs
    assert sent["message_thread_id"] == 99
    buttons = [button for row in sent["reply_markup"].inline_keyboard for button in row]
    index = ["/status", "/stop", "/loop pause", "/loop resume"].index(command)
    data = buttons[index].callback_data
    assert len(data.encode()) <= 64
    query = _query(data)
    await adapter._handle_callback_query(SimpleNamespace(callback_query=query), None)
    dispatched = adapter.handle_message.await_args.args[0]
    assert dispatched.text == command
    assert dispatched.source == event.source
    assert dispatched.internal is False
    assert dispatched.metadata["gateway_session_key"] == entry.session_key
    adapter._is_callback_user_authorized.assert_called_once()
    runner.session_store.peek_session_id.assert_called_once_with(entry.session_key)
    await adapter._handle_callback_query(SimpleNamespace(callback_query=query), None)
    adapter.handle_message.assert_awaited_once()  # Replays cannot apply twice.


@pytest.mark.asyncio
@pytest.mark.parametrize("mismatch", ["user", "chat", "topic", "message", "session", "expired", "unauthorized"])
async def test_control_rejects_changed_scope_and_expired_state(mismatch, monkeypatch):
    adapter, runner, event, entry = _context()
    await adapter.send_session_controls(runner, event, entry, "Current status")
    keyboard = adapter._bot.send_message.await_args.kwargs["reply_markup"]
    query = _query(keyboard.inline_keyboard[0][1].callback_data)
    if mismatch == "user":
        query.from_user.id = 8
    elif mismatch == "chat":
        query.message.chat_id = 999
    elif mismatch == "topic":
        query.message.message_thread_id = 100
    elif mismatch == "message":
        query.message.message_id = 43
    elif mismatch == "session":
        runner.session_store.peek_session_id.return_value = "replacement-session"
    elif mismatch == "expired":
        from plugins.platforms.telegram import session_controls
        monkeypatch.setattr(session_controls.time, "monotonic", lambda: float("inf"))
    elif mismatch == "unauthorized":
        adapter._is_callback_user_authorized.return_value = False
    await adapter._handle_callback_query(SimpleNamespace(callback_query=query), None)
    adapter.handle_message.assert_not_awaited()
    assert query.answer.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("busy", [False, True])
async def test_dispatch_rechecks_session_after_callback_admission_delay(busy):
    from gateway.run_inbound import GatewayInboundMixin

    adapter, runner, event, entry = _context()
    await adapter.send_session_controls(runner, event, entry, "Current status")
    keyboard = adapter._bot.send_message.await_args.kwargs["reply_markup"]
    query = _query(keyboard.inline_keyboard[0][1].callback_data)
    replies = []

    async def delayed_admission(control_event):
        runner.session_store.peek_session_id.return_value = "replacement-session"
        if busy:
            result = await GatewayInboundMixin._hm_busy_slash_or_photo(
                runner, control_event, control_event.source, entry.session_key)
        else:
            result = await GatewayInboundMixin._hm_dispatch_canonical_command(
                runner, control_event, control_event.source, entry.session_key, "stop")
        replies.append(result)

    adapter.handle_message.side_effect = delayed_admission
    await adapter._handle_callback_query(SimpleNamespace(callback_query=query), None)
    assert len(replies) == 1
    assert replies[0][0] is True and "expired" in replies[0][1]


@pytest.mark.asyncio
@pytest.mark.parametrize("send_fails", [False, True])
async def test_status_response_delivers_one_panel_or_falls_back_to_text(send_fails):
    from gateway.slash_commands_status import GatewayStatusCommandsMixin

    adapter, runner, event, entry = _context()
    entry.created_at = entry.updated_at = datetime.now()
    runner.async_session_store = SimpleNamespace(get_or_create_session=AsyncMock(return_value=entry))
    runner._running_agents = {}
    runner.adapters = {Platform.TELEGRAM: adapter}
    runner._queue_depth = lambda *args, **kwargs: 0
    runner._status_session_db_facts = AsyncMock(return_value=(None, {}, 0, {}))
    runner._cached_agent_for = lambda key: None
    runner._adapter_for_source = lambda source: adapter
    if send_fails:
        adapter._bot.send_message.side_effect = RuntimeError("transport unavailable")
    result = await GatewayStatusCommandsMixin._handle_status_command(runner, event)
    if send_fails:
        assert entry.session_id in result
        assert not getattr(adapter, "_session_controls", {})
    else:
        assert result == ""
        assert entry.session_id in adapter._bot.send_message.await_args.kwargs["text"]
        adapter._bot.send_message.assert_awaited_once()
