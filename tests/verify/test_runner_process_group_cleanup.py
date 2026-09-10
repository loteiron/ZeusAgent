"""Returning from verification means its actual child server has stopped."""

import os
import shlex
import signal
import socket
import sys
import time

import psutil
import pytest

from agent.verify import runner
from agent.verify.recipes import Recipe


pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX process-group signal semantics")


@pytest.mark.parametrize(
    ("behavior", "group_probe_error"),
    [
        ("delayed-exit", None),
        ("ignore-term", None),
        ("wrapper-exits", None),
        ("ignore-term", PermissionError),
        ("ignore-term", ProcessLookupError),
    ],
    ids=["delayed-exit", "ignore-term", "wrapper-exits", "probe-permission", "probe-missing"],
)
def test_verification_waits_for_the_server_after_its_wrapper_exits(tmp_path, monkeypatch, behavior, group_probe_error):
    if group_probe_error:
        actual_killpg = os.killpg

        def unavailable_probe(pgid, sig):
            # macOS returned EPERM for signal 0 during native cancellation.
            # Probe failures cannot replace observing the still-live child;
            # real TERM/KILL delivery remains active throughout this test.
            if sig == 0:
                raise group_probe_error("group probe is unavailable during teardown")
            return actual_killpg(pgid, sig)

        monkeypatch.setattr(os, "killpg", unavailable_probe)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = tmp_path / "server.py"
    server.write_text(
        "import http.server, os, signal, socketserver, sys, time\n"
        "from pathlib import Path\n"
        "class Server(http.server.HTTPServer):\n"
        "    def server_bind(self):\n"
        "        socketserver.TCPServer.server_bind(self)\n"
        "        self.server_name, self.server_port = self.server_address[:2]\n"
        "def terminate(*args):\n"
        "    Path('term-received').write_text('yes')\n"
        f"    if {behavior!r} == 'ignore-term': return\n"
        "    time.sleep(0.4)\n"
        "    server.server_close()\n"
        "    Path('graceful-exit').write_text('yes')\n"
        "    raise SystemExit(0)\n"
        "signal.signal(signal.SIGTERM, terminate)\n"
        f"server = Server(('127.0.0.1', {port}), http.server.SimpleHTTPRequestHandler)\n"
        "Path('child.pid').write_text(str(os.getpid()))\n"
        "server.serve_forever(poll_interval=0.01)\n",
        encoding="utf-8",
    )
    wrapper = tmp_path / "wrapper.py"
    wrapper.write_text(
        "import os, subprocess, sys, time\nfrom pathlib import Path\n"
        "Path('group.pid').write_text(str(os.getpgrp()))\n"
        "child = subprocess.Popen([sys.executable, 'server.py'])\n"
        + ("\n" if behavior == "wrapper-exits" else "child.wait()\n"),
        encoding="utf-8",
    )
    # Real signals and sockets stay in use. Shorten only the escalation grace
    # for the deliberately uncooperative child, not its startup/readiness limit.
    if behavior == "ignore-term":
        monkeypatch.setattr(runner, "_PROCESS_TERMINATE_GRACE", 0.2, raising=False)
    recipe = Recipe(name="owned child server", start=shlex.join([sys.executable, str(wrapper)]), port=port)
    child = None
    started = time.monotonic()
    try:
        result = runner.run_verify(tmp_path, recipe, phases=("start",), ready_timeout=3)
        assert result.ok, result.to_dict()
        assert result.readiness.status_code == 200
        with socket.socket() as probe:
            probe.settimeout(0.5)
            assert probe.connect_ex(("127.0.0.1", port)) != 0, "verification left its server listening"
        assert (tmp_path / "term-received").exists(), "the owned server did not receive termination"
        if behavior != "ignore-term":
            assert (tmp_path / "graceful-exit").exists(), "teardown did not allow graceful child cleanup"
        pid = int((tmp_path / "child.pid").read_text(encoding="utf-8"))
        try:
            child = psutil.Process(pid)
        except psutil.NoSuchProcess:
            pass
        else:
            assert not child.is_running() or child.status() == psutil.STATUS_ZOMBIE
        assert time.monotonic() - started < 6, "bounded cleanup stalled after the wrapper exited"
    finally:
        # A red run must also leave the test machine clean. The recorded group
        # was created by run_verify(start_new_session=True), never our own group.
        group_file = tmp_path / "group.pid"
        if group_file.exists():
            pgid = int(group_file.read_text(encoding="utf-8"))
            assert pgid != os.getpgrp()
            try:
                os.killpg(pgid, signal.SIGKILL)  # windows-footgun: ok — this test is POSIX-only
            except ProcessLookupError:
                pass
