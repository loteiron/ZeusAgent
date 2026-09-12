from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from gateway.config import GatewayConfig, Platform, PlatformConfig
from gateway.platforms.event import MessageEvent, MessageType
from gateway.run import GatewayRunner
from gateway.session import SessionSource


def make_runner():
    runner = object.__new__(GatewayRunner)
    runner.config = GatewayConfig(platforms={Platform.TELEGRAM: PlatformConfig(enabled=True, extra={"allow_from": ["owner"], "allow_admin_from": ["owner"]})})
    runner._is_session_running = lambda key: False
    runner._resolve_profile_home_for_source = lambda source: None
    runner._normalize_source_for_session_key = lambda source: source
    runner._session_key_for_source = lambda source: "test-session"
    runner._record_model_switch = AsyncMock()
    runner._check_slash_access = lambda source, command: None
    runner._adapter_for_source = lambda source: SimpleNamespace(delete_message=AsyncMock(return_value=True))
    runner._hm_pending_reply_intercepts = AsyncMock(side_effect=AssertionError("secret reached ordinary reply interception"))
    runner._is_user_authorized_for_source = lambda source: True
    runner._scale_to_zero_note_real_inbound = Mock()
    runner._hm_pre_gateway_dispatch_hook = Mock(side_effect=AssertionError("secret reached plugins"))
    return runner


def event(text, *, user="owner", platform=Platform.TELEGRAM, chat_type="dm"):
    return MessageEvent(text=text, message_type=MessageType.COMMAND, message_id="1", source=SessionSource(platform=platform, user_id=user, chat_id=user, chat_type=chat_type))


@pytest.mark.asyncio
async def test_private_setup_uses_sensitive_dispatch_and_scrubs_the_event(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("ZEUS_HOME", str(tmp_path))
    runner = make_runner()
    message = event("/provider set http://127.0.0.1:8999/v1 model test-private-value")
    result = await runner._handle_message(message)
    assert "Saved custom provider" in result
    assert "test-private-value" not in result + message.text + caplog.text
    runner._record_model_switch.assert_awaited_once()
    runner._hm_pre_gateway_dispatch_hook.assert_not_called()
    runner._hm_pending_reply_intercepts.assert_not_awaited()
    assert not (tmp_path / "state.db").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("kw", [{"user": "guest"}, {"chat_type": "group"}, {"platform": Platform.DISCORD}])
async def test_setup_is_restricted_to_explicit_telegram_owner(tmp_path, monkeypatch, kw):
    monkeypatch.setenv("ZEUS_HOME", str(tmp_path))
    runner = make_runner()
    message = event("/provider set http://127.0.0.1:8999/v1 model test-private-value", **kw)
    result = await runner._handle_message(message)
    assert "Saved" not in result
    assert "test-private-value" not in message.text + result
    assert not (tmp_path / ".env").exists()


@pytest.mark.asyncio
async def test_busy_setup_returns_immediately_without_changing_route(tmp_path, monkeypatch):
    monkeypatch.setenv("ZEUS_HOME", str(tmp_path))
    runner = make_runner()
    runner._is_session_running = lambda key: True
    result = await runner._handle_message(event("/provider set http://127.0.0.1:8999/v1 model test-private-value"))
    assert "running" in result.lower()
    assert not (tmp_path / ".env").exists()


@pytest.mark.asyncio
async def test_source_profile_owns_both_authorization_and_saved_credential(tmp_path, monkeypatch):
    primary = tmp_path / "primary"
    secondary = tmp_path / "profiles" / "secondary"
    primary.mkdir()
    secondary.mkdir(parents=True)
    monkeypatch.setenv("ZEUS_HOME", str(primary))
    runner = make_runner()
    runner.config.multiplex_profiles = True
    runner._resolve_profile_home_for_source = lambda source: secondary
    secondary_adapter = SimpleNamespace(config=PlatformConfig(enabled=True, extra={"allow_from": ["secondary-owner"]}), delete_message=AsyncMock(return_value=True))
    runner._adapter_for_source = lambda source: secondary_adapter
    denied = await runner._handle_message(event("/provider set http://127.0.0.1:8999/v1 model test-private-value"))
    assert "Saved" not in denied
    accepted = await runner._handle_message(event("/provider set http://127.0.0.1:8999/v1 model test-private-value", user="secondary-owner"))
    assert "Saved custom provider" in accepted
    assert (secondary / ".env").exists()
    assert not (primary / ".env").exists()


@pytest.mark.asyncio
async def test_base_adapter_never_queues_or_starts_a_background_task_for_credentials():
    import asyncio
    from gateway.platforms.base import BasePlatformAdapter
    class Adapter(BasePlatformAdapter):
        async def connect(self, **kwargs): pass
        async def disconnect(self): pass
        async def send(self, *args, **kwargs): pass
        async def get_chat_info(self, *args): return {}
    adapter = Adapter(PlatformConfig(enabled=True), Platform.TELEGRAM)
    adapter._message_handler = AsyncMock()
    adapter._dispatch_inline_reply = AsyncMock()
    adapter._start_session_processing = Mock(side_effect=AssertionError("credential entered task recovery"))
    message = event("/provider set http://127.0.0.1:8999/v1 model test-private-value")
    for busy in (False, True):
        if busy:
            adapter._active_sessions[adapter._event_session_key(message)] = asyncio.Event()
        await adapter.handle_message(message)
    assert adapter._dispatch_inline_reply.await_count == 2
    assert not adapter._pending_messages


@pytest.mark.asyncio
@pytest.mark.parametrize("entrypoint", ["_handle_text_message", "_handle_command"])
async def test_telegram_credential_commands_bypass_transport_batching(entrypoint):
    from plugins.platforms.telegram.adapter import TelegramAdapter

    adapter = TelegramAdapter(PlatformConfig(enabled=True))
    message = event("/provider set http://127.0.0.1/v1 model " + "k" * 4000)
    transport_message = SimpleNamespace(text=message.text)
    update = SimpleNamespace(message=transport_message, effective_message=transport_message)
    adapter._is_user_authorized_from_message = lambda msg: True
    adapter._gate_or_observe = lambda *args: True
    adapter._should_process_message = lambda *args, **kwargs: True
    adapter._ensure_forum_commands = AsyncMock()
    adapter._build_triggered_event = AsyncMock(return_value=message)
    adapter._enqueue_text_event = Mock(side_effect=AssertionError("credential entered transport batching"))
    adapter.handle_message = AsyncMock()
    await getattr(adapter, entrypoint)(update, None)
    adapter.handle_message.assert_awaited_once_with(message)


@pytest.mark.asyncio
async def test_saved_provider_reaches_next_turn_and_restart_without_persisting_key(tmp_path, monkeypatch):
    from gateway.session import SessionStore, build_session_key
    from zeus_cli.runtime_provider import resolve_runtime_provider

    monkeypatch.setenv("ZEUS_HOME", str(tmp_path))
    runner = make_runner()
    del runner._record_model_switch  # Exercise the real persistence/activation path.
    runner._session_model_overrides = {}
    runner.session_store = SessionStore(tmp_path / "sessions", runner.config)
    message = event("/provider set http://127.0.0.1:8999/v1 custom-model test-private-value responses")
    runner._session_key_for_source = build_session_key
    runner.session_store.get_or_create_session(message.source)
    result = await runner._handle_message(message)
    assert "Saved custom provider" in result
    key = build_session_key(message.source)
    model, runtime = runner._apply_session_model_override(key, "old-model", {})
    assert model == "custom-model"
    assert runtime["api_key"] == "test-private-value"
    assert runtime["api_mode"] == "codex_responses"
    reopened = SessionStore(tmp_path / "sessions", runner.config)
    persisted = reopened.get_model_override(key)
    assert persisted["model"] == model
    assert "api_key" not in persisted
    resolved = resolve_runtime_provider(requested=persisted["provider"], target_model=persisted["model"])
    assert resolved["api_key"] == "test-private-value"
    assert resolved["api_mode"] == runtime["api_mode"]
    for path in tmp_path.rglob("*"):
        if path.is_file() and path.name != ".env":
            assert b"test-private-value" not in path.read_bytes()
