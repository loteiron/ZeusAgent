"""A served secondary's api_server/webhook are MIRRORS of the default's listener (``/p/<profile>/...``),
never adapters of their own, so the multiplexer record has no ``<profile>:api_server`` entry. Every
status reader used to fall through to ``pending_restart``: the Desktop Messaging card and Command
Center read "Restart needed" forever for a platform that was answering. The mirror must project as the
default's live state plus the URL the client has to call; ``/api/status?profile=`` names the profiles a
restart of the shared gateway would blip.
"""

from __future__ import annotations

import json
import os

import pytest


@pytest.fixture
def served_root(tmp_path, monkeypatch):
    root = tmp_path / "zeus"
    (root / "profiles" / "alpha").mkdir(parents=True)
    (root / "config.yaml").write_text("gateway: {multiplex_profiles: true}\n")
    (root / "gateway.pid").write_text(json.dumps({"pid": os.getpid(), "zeus_home": str(root)}))
    (root / "gateway_state.json").write_text(json.dumps({
        "pid": os.getpid(), "zeus_home": str(root), "gateway_state": "running",
        "served_profiles": ["default", "alpha", "beta"],
        "platforms": {
            "api_server": {"state": "connected", "listener_base": "http://127.0.0.1:45719"},
            "webhook": {"state": "fatal", "error_code": "port_in_use"},
            "alpha:telegram": {"state": "connected"},
        }}))
    monkeypatch.setenv("ZEUS_HOME", str(root))
    monkeypatch.delenv("GATEWAY_MULTIPLEX_PROFILES", raising=False)
    import zeus_constants
    monkeypatch.setattr(zeus_constants, "_default_zeus_root_memo", None)
    return root


def test_served_profile_projects_the_default_listener_mirrors_with_their_url(served_root):
    from gateway.status import profile_platforms_from_multiplexer, resolve_gateway_liveness
    alpha = served_root / "profiles" / "alpha"
    live = resolve_gateway_liveness(profile_dir=alpha, health_probe=None, use_cache=False)
    plats = profile_platforms_from_multiplexer(live.runtime, "alpha")
    # The mirror inherits the default's live state and points at the profile's own prefix.
    assert plats["api_server"]["state"] == "connected"
    assert plats["api_server"]["ingress_url"] == "http://127.0.0.1:45719/p/alpha/v1"
    # A dead default listener is dead for the profile too — never "connected" by fiat.
    assert "webhook" not in plats
    assert plats["telegram"] == {"state": "connected"}
    # The default profile keeps its own un-prefixed entries; nothing is mirrored onto it.
    assert "ingress_url" not in profile_platforms_from_multiplexer(live.runtime, "default").get("api_server", {})


def test_messaging_card_for_a_served_profile_reads_connected_not_restart_needed(served_root, monkeypatch):
    from zeus_cli.web_routers import messaging
    monkeypatch.setattr(messaging, "_platform_enablement", lambda *a, **k: (True, True, None))
    entry = {"id": "api_server", "name": "API server", "description": "", "docs_url": "", "env_vars": [],
             "required_env": []}
    alpha = served_root / "profiles" / "alpha"
    [payload] = messaging._platform_payloads(alpha, [entry])
    assert payload["gateway_running"] is True
    assert payload["state"] == "connected", payload
    assert payload["ingress_url"] == "http://127.0.0.1:45719/p/alpha/v1"


@pytest.mark.asyncio
async def test_default_gateway_also_lists_the_profiles_its_restart_affects(served_root, monkeypatch):
    from zeus_cli.web_routers import status
    monkeypatch.setattr(status, "get_running_pid_cached", lambda *a, **k: os.getpid())
    monkeypatch.setattr(status, "_load_configured_gateway_platforms", lambda: {"api_server"})
    payload = await status._resolve_gateway_status(served_root, None)
    assert payload["gateway_running"] is True
    assert payload["gateway_shared_with"] == ["default", "alpha", "beta"]


@pytest.mark.asyncio
@pytest.mark.parametrize("verb", ["start", "stop"])
async def test_served_profile_rest_lifecycle_refuses_before_spawning(served_root, monkeypatch, verb):
    from fastapi import HTTPException
    from zeus_cli.web_routers import ops
    monkeypatch.setattr(ops, "_spawn_zeus_action", lambda *a, **k: pytest.fail("must not spawn"))
    with pytest.raises(HTTPException) as error:
        await getattr(ops, f"{verb}_gateway")("alpha")
    assert error.value.status_code == 409
    assert "alpha" in error.value.detail and "multiplexer" in error.value.detail


def test_profile_restart_child_does_not_inherit_the_dashboard_credentials(served_root, monkeypatch):
    from zeus_cli.web_server_gateway import _profile_action_environment
    (served_root / ".env").write_text("PRIVATE_SERVICE_ALIAS=fixture-root-secret\n", encoding="utf-8")
    monkeypatch.setenv("PRIVATE_SERVICE_ALIAS", "fixture-root-secret")
    monkeypatch.setenv("_ZEUS_GATEWAY", "1")
    child = _profile_action_environment(["-p", "alpha", "gateway", "restart"])
    assert "PRIVATE_SERVICE_ALIAS" not in child
    assert "_ZEUS_GATEWAY" not in child
    assert child["ZEUS_HOME"] == str(served_root / "profiles" / "alpha")
    assert child["ZEUS_NONINTERACTIVE"] == "1"
