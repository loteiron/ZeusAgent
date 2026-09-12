"""Zeus listeners can coexist with the upstream defaults on the same host."""
import argparse
import inspect

import pytest

from gateway.config import PlatformConfig
from gateway.platforms.api_server import APIServerAdapter
from zeus_cli.main_dashboard import _parse_dashboard_runtime
from zeus_cli.subcommands.dashboard import build_dashboard_parser, build_serve_parser
from zeus_cli.web_server import start_server
from zeus_cli.web_server_gateway import _profile_platform_ports


def parsers():
    root = argparse.ArgumentParser()
    build_dashboard_parser(root.add_subparsers(dest="command"),
                           cmd_dashboard=lambda args: None, cmd_dashboard_register=lambda args: None)
    return root, build_serve_parser(cmd_dashboard=lambda args: None)


def test_default_listeners_do_not_overlap_upstream_and_probe_matches_launch(tmp_path):
    root, lean = parsers()
    dashboard = root.parse_args(["dashboard"])
    api_port = APIServerAdapter(PlatformConfig(enabled=True))._port
    ports = {dashboard.port, api_port}
    assert len(ports) == 2
    assert ports.isdisjoint({9119, 8642})
    assert dashboard.port == lean.parse_args([]).port
    assert dashboard.port == inspect.signature(start_server).parameters["port"].default
    assert _profile_platform_ports(tmp_path, {"platforms": {"api_server": {"state": "connected"}}}) == {
        "api_server": api_port,
    }
    for mode in ("dashboard", "serve"):
        assert _parse_dashboard_runtime(f"zeus {mode}") == (mode, dashboard.host, dashboard.port)


@pytest.mark.parametrize("port", [0, 9119, 12345])
def test_explicit_ports_including_auto_assignment_remain_available(port):
    root, lean = parsers()
    for mode in ("dashboard", "serve"):
        assert root.parse_args([mode, "--port", str(port)]).port == port
        assert _parse_dashboard_runtime(f"zeus {mode} --port={port}")[2] == port
    assert lean.parse_args(["--port", str(port)]).port == port
    assert APIServerAdapter(PlatformConfig(enabled=True, extra={"port": port}))._port == port
