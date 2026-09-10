"""Short-lived Telegram controls bound to one user's current conversation."""

from __future__ import annotations

import copy
import secrets
import time

from gateway.platforms.base import SendResult
from gateway.platforms.event import MessageEvent, MessageType

_ACTIONS = (("Status", "/status"), ("Stop", "/stop"),
            ("Pause loop", "/loop pause"), ("Resume loop", "/loop resume"))
_TTL_SECONDS = 30 * 60
_MAX_PANELS = 128


async def send_controls(adapter, runner, event, entry, text: str) -> SendResult:
    from plugins.platforms.telegram.adapter import InlineKeyboardButton, InlineKeyboardMarkup

    if not event.source.user_id:
        return SendResult(success=False, error="Controls require a user identity")
    state = getattr(adapter, "_session_controls", None)
    if state is None:
        state = adapter._session_controls = {}
    now = time.monotonic()
    for token, pending in list(state.items()):
        if now >= pending["expires_at"]:
            state.pop(token, None)
    while len(state) >= _MAX_PANELS:
        state.pop(next(iter(state)))
    token = secrets.token_urlsafe(12)
    source = copy.copy(event.source)

    def build():
        buttons = [InlineKeyboardButton(label, callback_data=f"zc:{token}:{index}")
                   for index, (label, _) in enumerate(_ACTIONS)]

        def remember(message):
            state[token] = {"source": source, "runner": runner, "session_key": entry.session_key,
                            "session_id": entry.session_id, "message_id": str(message.message_id),
                            "expires_at": now + _TTL_SECONDS}

        return adapter.format_message(text), InlineKeyboardMarkup(adapter._rows_of_two(buttons)), remember

    metadata = runner._thread_metadata_for_source(source, runner._reply_anchor_for_event(event))
    return await adapter._send_prompt("session controls", source.chat_id, metadata, build,
                                      thread_id=source.thread_id, reply_to_mode=adapter._reply_to_mode)


async def handle_control(adapter, query, data: str, cb: dict) -> None:
    state = getattr(adapter, "_session_controls", {})
    parts = data.split(":")
    pending = state.get(parts[1]) if len(parts) == 3 else None
    if pending is None or time.monotonic() >= pending["expires_at"]:
        if len(parts) == 3:
            state.pop(parts[1], None)
        await query.answer(text="Controls expired. Open /status again.")
        return
    source = pending["source"]
    message = getattr(query, "message", None)
    if (str(getattr(query.from_user, "id", "")) != str(source.user_id)
            or str(cb.get("chat_id") or "") != str(source.chat_id)
            or str(cb.get("thread_id") or "") != str(source.thread_id or "")
            or str(getattr(message, "message_id", "")) != pending["message_id"]):
        await query.answer(text="These controls belong to another conversation or user.")
        return
    if not parts[2].isdigit() or int(parts[2]) >= len(_ACTIONS):
        await query.answer(text="Unknown control.")
        return
    runner = pending["runner"]
    with runner._profile_scope_for_source(source):
        if not await adapter._callback_authorized(query, cb, "You are not authorized to control this session."):
            return
        if runner.session_store.peek_session_id(pending["session_key"]) != pending["session_id"]:
            state.pop(parts[1], None)
            await query.answer(text="The session changed. Open /status for current controls.")
            return
        # Claim before handing off: duplicate taps cannot execute twice. The ordinary
        # dispatcher rechecks the durable ID too, after any background admission delay.
        state.pop(parts[1], None)
        await query.answer()
        event = MessageEvent(
            text=_ACTIONS[int(parts[2])][1], message_type=MessageType.COMMAND,
            source=copy.copy(source), message_id=pending["message_id"],
            metadata={"gateway_session_key": pending["session_key"],
                      "gateway_control_session_id": pending["session_id"]},
        )
        await adapter.handle_message(event)
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass  # Deleting an old panel does not affect the admitted action.
