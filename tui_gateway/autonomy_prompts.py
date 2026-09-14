"""Dismiss the owner's pending questions without inventing answers or credentials."""


def release_autonomous_prompts(sid, lock, pending, payloads, answers, emit):
    expired = []
    with lock:
        for rid, (owner, event) in list(pending.items()):
            kind, _payload = payloads.get(rid, ("", {}))
            if owner == sid and kind in {"clarify.request", "sudo.request", "secret.request"}:
                # No invented selection. clarify_tool returns an autonomous instruction
                # after this callback unwinds, without a user_response field.
                answers[rid] = ""
                event.set()
                expired.append((rid, kind))
    for rid, kind in expired:
        emit(kind.removesuffix(".request") + ".expire", sid, {"request_id": rid})
