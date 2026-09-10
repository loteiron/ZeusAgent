"""Profile arguments must not be confused with the Zeus executable."""

import pytest

from cron import lifecycle_guard


@pytest.mark.parametrize("selector", ["-p zeus", "--profile=zeus", "--profile 'zeus'"])
@pytest.mark.parametrize("current", [None, "athena", "zeus"])
def test_profile_named_like_executable(monkeypatch, selector, current):
    monkeypatch.setattr(lifecycle_guard, "_current_profile_name", lambda: current)
    command = f"zeus {selector} gateway restart"
    assert lifecycle_guard.contains_gateway_lifecycle_command(command) is (current == "zeus")


@pytest.mark.parametrize("tail", [
    "; zeus gateway stop",
    " && zeus -p athena gateway restart",
    "\nzeus --profile='athena' gateway stop",
    '; echo "$(zeus gateway restart)"',
])
def test_sibling_selector_does_not_hide_later_self_restart(monkeypatch, tail):
    monkeypatch.setattr(lifecycle_guard, "_current_profile_name", lambda: "athena")
    assert lifecycle_guard.contains_gateway_lifecycle_command(
        "zeus -p zeus gateway restart" + tail
    )


def test_profile_argument_command_substitution_stays_blocked(monkeypatch):
    monkeypatch.setattr(lifecycle_guard, "_current_profile_name", lambda: "athena")
    assert lifecycle_guard.contains_gateway_lifecycle_command(
        'zeus -p "$(zeus gateway stop)" gateway restart'
    )
