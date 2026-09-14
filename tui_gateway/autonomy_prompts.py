"""Release already-visible clarification cards when their owner enables autonomy."""


def release_autonomous_prompts(sid, lock, pending, payloads, answers, emit):
    expired = []
    with lock:
        for rid, (owner, event) in list(pending.items()):
            kind, _payload = payloads.get(rid, ("", {}))
            if owner == sid and kind == "clarify.request":
                # No invented selection. clarify_tool returns an autonomous instruction
                # after this callback unwinds, without a user_response field.
                answers[rid] = ""
                event.set()
                expired.append(rid)
    for rid in expired:
        emit("clarify.expire", sid, {"request_id": rid})
