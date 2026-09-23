from unittest.mock import AsyncMock, MagicMock

import pytest

from gateway.config import PlatformConfig
from gateway.platforms.base import SendResult
from gateway.stream_consumer import GatewayStreamConsumer, StreamConsumerConfig
from plugins.platforms.telegram.adapter import TelegramAdapter


@pytest.mark.asyncio
async def test_deferred_preview_does_not_mark_unseen_text_as_delivered():
    adapter = TelegramAdapter(PlatformConfig(enabled=True, token="fake"))
    adapter._rich_send_disabled = True
    adapter._bot = MagicMock()
    adapter._bot.edit_message_text = AsyncMock(return_value=MagicMock())
    consumer = GatewayStreamConsumer(adapter, "123", StreamConsumerConfig(cursor="|"))
    consumer._message_id = "900"
    consumer._already_sent = True
    assert await consumer._edit_existing("Answer|", finalize=False, is_turn_final=False)
    assert consumer._last_sent_text == "Answer|"
    consumer._flood_strikes = 1
    assert await consumer._edit_existing("Answer is 42|", finalize=False, is_turn_final=False)
    assert adapter._bot.edit_message_text.await_count == 1
    assert consumer._last_sent_text == "Answer|"
    assert consumer._flood_strikes == 1
    adapter.edit_message = AsyncMock(return_value=SendResult(
        success=False, error="Flood control exceeded. Retry in 9 seconds", retry_after=9))
    assert not await consumer._edit_existing("Answer is 42", finalize=True, is_turn_final=True)
    assert consumer._fallback_prefix == "Answer"
    assert consumer._current_edit_interval >= 9
