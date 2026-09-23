"""The current compacted image turn must replay its injected context after restart."""
import copy
from types import SimpleNamespace

import pytest

from agent.turn_context import _stamp_api_content_sidecar
from zeus_state import SessionDB


@pytest.mark.parametrize("racing_message", [False, True])
def test_multimodal_context_backfill_preserves_images_and_other_turns(tmp_path, racing_message):
    path = tmp_path / "state.db"
    original = [{"type": "text", "text": "Explain this project diagram"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,dGVzdA=="}}]
    messages = [{"role": "user", "content": copy.deepcopy(original)}]
    with SessionDB(db_path=path) as db:
        db.create_session("s", source="cli")
        db.append_message("s", "user", content="older turn")
        db.append_message("s", "assistant", content="older answer")
        db.append_message("s", "user", content=copy.deepcopy(original))
        if racing_message:
            db.append_message("s", "user", content="newer message")
        agent = SimpleNamespace(_session_db=db, session_id="s", _last_compaction_in_place=True)
        _stamp_api_content_sidecar(agent, messages, 0, "- Project uses Python", "PLUGIN CONTEXT",
                                   preflight_compressed=True)
    with SessionDB(db_path=path) as reopened:
        replay = reopened.get_messages_as_conversation("s")
    assert replay[0]["content"] == "older turn"
    assert replay[1]["content"] == "older answer"
    assert replay[2]["content"][:2] == original
    if racing_message:
        assert replay[2]["content"] == original
        assert replay[3]["content"] == "newer message"
    else:
        assert replay[2]["content"] == messages[0]["content"]
        assert "PLUGIN CONTEXT" in replay[2]["content"][-1]["text"]
        assert len(replay) == 3
