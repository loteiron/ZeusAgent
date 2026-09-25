import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


def _plain(s: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", s)


@pytest.fixture
def cli_stub(monkeypatch):
    from cli import ZeusAgentCLI
    import cli as climod

    cli = ZeusAgentCLI.__new__(ZeusAgentCLI)
    cli.show_reasoning = False
    cli.final_response_markdown = "raw"
    cli.show_timestamps = False
    cli._reset_stream_state()
    emitted = []
    monkeypatch.setattr(climod, "_cprint", lambda s: emitted.append(s))
    monkeypatch.setattr(climod, "_terminal_width_for_streaming", lambda: 74)
    monkeypatch.setattr(ZeusAgentCLI, "_scrollback_box_width", lambda self: 74)
    return cli, emitted


def test_answer_streams_before_turn_end_after_reasoning(cli_stub):
    """#47116: with show_reasoning on, the reasoning box closes on the first content token so the
    answer streams mid-turn instead of being held until end of turn."""
    cli, emitted = cli_stub
    cli.show_reasoning = True
    cli._stream_reasoning_delta("thinking about it\n")
    cli._stream_delta("First answer line.\n")
    # No _flush_stream(): the line must already be on screen mid-turn.
    lines = [_plain(e) for e in emitted]
    answer = [i for i, l in enumerate(lines) if "First answer line." in l]
    assert answer, lines
    reasoning = next(i for i, l in enumerate(lines) if "thinking about it" in l)
    assert reasoning < answer[0]


def test_late_reasoning_does_not_reopen_box_inside_answer(cli_stub):
    cli, emitted = cli_stub
    cli.show_reasoning = True
    cli._stream_reasoning_delta("early thought\n")
    cli._stream_delta("Answer.\n")
    cli._stream_reasoning_delta("late thought\n")
    cli._flush_stream()
    assert not any("late thought" in _plain(e) for e in emitted), emitted
