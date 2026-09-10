"""Readiness evidence must describe a healthy HTTP response within its budget."""

import contextlib
import http.server
import socket
import sys
import threading
import time
import urllib.request

import pytest

from agent.verify.recipes import Recipe
from agent.verify.runner import _poll_readiness, run_verify
from tests.fakes import loopback_http_server


@contextlib.contextmanager
def _server(statuses=(200,), *, delay=0, startup_delay=0):
    received = []
    stop = threading.Event()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/__fixture_ready":
                self.send_response(200)
                self.end_headers()
                return
            index = len(received)
            received.append(self.path)
            stop.wait(delay)
            if stop.is_set():
                return
            self.send_response(statuses[min(index, len(statuses) - 1)])
            self.end_headers()

        def log_message(self, *_args):
            pass

    server = loopback_http_server.LoopbackHTTPServer(("127.0.0.1", 0), Handler)
    def serve():
        stop.wait(startup_delay)
        server.serve_forever(poll_interval=0.01)

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        # Finish actual socket/thread startup before measuring a deliberately
        # short request budget. This probe never consumes the tested sequence.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f"http://127.0.0.1:{server.server_port}/__fixture_ready", timeout=5) as response:
            assert response.status == 200
        yield f"http://127.0.0.1:{server.server_port}/health", received
    finally:
        stop.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_readiness_waits_through_warmup_until_healthy_response():
    with _server((503, 503, 200)) as (url, received):
        assert _poll_readiness(url, 1, interval=0.01) == (True, 200, None)
        assert len(received) == 3


def test_fixture_finishes_startup_before_measuring_a_short_readiness_budget():
    with _server((503,), startup_delay=0.3) as (url, received):
        ready, code, _error = _poll_readiness(url, 0.12, interval=0.01)
        assert not ready
        assert code == 503
        assert received


@pytest.mark.parametrize("status", [404, 500, 503])
def test_permanent_http_failure_remains_failed_with_actual_status(status):
    with _server((status,)) as (url, received):
        ready, code, error = _poll_readiness(url, 0.12, interval=0.01)
        assert not ready
        assert code == status
        assert str(status) in error
        assert len(received) > 1


@pytest.mark.parametrize("status", [200, 204, 302, 304])
def test_success_and_redirect_statuses_are_readiness_only(status):
    with _server((status,)) as (url, _received):
        assert _poll_readiness(url, 0.2, interval=0.01) == (True, status, None)


def test_slow_response_cannot_take_the_default_five_second_request_budget():
    with _server(delay=2) as (url, received):
        started = time.monotonic()
        ready, _code, error = _poll_readiness(url, 0.2)
        elapsed = time.monotonic() - started
        assert not ready
        assert error
        assert received
        # Leave scheduling tolerance while rejecting the old 2s response wait
        # and the old extra 1s poll sleep after the budget has expired.
        assert elapsed < 0.8, f"readiness exceeded its 0.2s budget: {elapsed:.3f}s"


def test_local_readiness_does_not_accept_a_proxy_response(monkeypatch):
    with _server((200,)) as (proxy_url, proxy_requests), _server((503,)) as (url, local_requests):
        monkeypatch.setenv("http_proxy", proxy_url)
        monkeypatch.setenv("HTTP_PROXY", proxy_url)
        monkeypatch.delenv("NO_PROXY", raising=False)
        monkeypatch.delenv("no_proxy", raising=False)
        ready, code, _error = _poll_readiness(url, 0.12, interval=0.01)
        assert not ready
        assert code == 503
        assert local_requests
        assert not proxy_requests


def test_a_missing_readiness_route_cannot_verify_the_real_started_project(tmp_path):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    recipe = Recipe(
        name="missing health route",
        start=loopback_http_server.command(port),
        port=port,
        readiness_path="/missing-health-route",
    )
    result = run_verify(tmp_path, recipe, phases=("start",), ready_timeout=3)
    assert result.readiness.status_code == 404
    assert not result.readiness.ready
    assert not result.ok
    assert result.to_dict()["ok"] is False
    with socket.socket() as probe:
        probe.settimeout(0.5)
        assert probe.connect_ex(("127.0.0.1", port)) != 0, "verification left its server running"


@pytest.mark.parametrize("dns_delay", [0, 4], ids=["unavailable", "stalled"])
def test_loopback_fixture_starts_even_when_reverse_dns_is_unavailable(tmp_path, dns_delay):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    launcher = tmp_path / "dns_unavailable.py"
    launcher.write_text(
        "import runpy, socket, sys, time\n"
        "def unavailable(*args):\n"
        f"    time.sleep({dns_delay})\n"
        "    raise AssertionError('Loopback fixture attempted external reverse DNS')\n"
        "socket.getfqdn = unavailable\n"
        f"sys.argv = [{loopback_http_server.__file__!r}, {str(port)!r}]\n"
        f"runpy.run_path({loopback_http_server.__file__!r}, run_name='__main__')\n",
        encoding="utf-8",
    )
    recipe = Recipe(name="DNS-independent HTTP fixture", start=f'"{sys.executable}" "{launcher}"', port=port)
    result = run_verify(tmp_path, recipe, phases=("start",), ready_timeout=3)
    assert result.readiness.ready, result.readiness.to_dict()
    assert result.readiness.status_code == 200
    assert result.ok
    with socket.socket() as probe:
        probe.settimeout(0.5)
        assert probe.connect_ex(("127.0.0.1", port)) != 0, "verification left its server running"
