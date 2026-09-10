"""The independent source build cannot silently replace itself with upstream."""
from argparse import Namespace
import asyncio

import pytest

from zeus_cli import banner, distribution


@pytest.mark.parametrize("check,expected", [(True, 0), (False, 2)])
def test_source_updates_do_not_invoke_an_external_process(monkeypatch, capsys, check, expected):
    def forbidden(*args, **kwargs):
        pytest.fail("A source-only update attempted to invoke a subprocess")
    monkeypatch.setattr(banner.subprocess, "run", forbidden)
    assert banner.check_for_updates() is None
    assert distribution.handle_source_update(Namespace(check=check, plan=False)) == expected
    assert "No ZeusAgent release channel" in capsys.readouterr().out


def test_dashboard_source_update_is_refused_before_spawning(monkeypatch):
    from zeus_cli.web_routers import actions

    def forbidden(*args, **kwargs):
        pytest.fail("Source-only dashboard attempted to start an updater")
    monkeypatch.setattr(actions, "_spawn_zeus_action", forbidden)
    response = asyncio.run(actions.update_zeus())
    assert response["ok"] is False
    assert response["pid"] is None
    assert response["error"] == "source_distribution"
