"""Cancelling a recipe must stop the real owned subprocess before propagating."""
import subprocess
import sys
import time
from types import SimpleNamespace

import psutil
import pytest

from agent.deadline import kill_process_tree
from agent.verify import runner


def test_interrupted_phase_stops_its_child(tmp_path, monkeypatch):
    marker = tmp_path / "child.pid"
    (tmp_path / "sleeper.py").write_text(
        "import os, time\nfrom pathlib import Path\n"
        "Path('child.pid').write_text(str(os.getpid()))\ntime.sleep(60)\n",
        encoding="utf-8",
    )
    processes = []
    child = None

    def launch(*args, **kwargs):
        proc = subprocess.Popen(*args, **kwargs)
        processes.append(proc)
        real_wait = proc.wait
        interrupted = False

        def wait(timeout=None):
            nonlocal interrupted, child
            if not interrupted:
                interrupted = True
                deadline = time.monotonic() + 15
                while not marker.exists() and time.monotonic() < deadline:
                    time.sleep(0.02)
                assert marker.exists(), "the real child never started"
                child = psutil.Process(int(marker.read_text(encoding="utf-8")))
                raise KeyboardInterrupt("user cancelled verification")
            return real_wait(timeout=timeout)

        proc.wait = wait
        return proc

    monkeypatch.setattr(runner, "subprocess", SimpleNamespace(Popen=launch, TimeoutExpired=subprocess.TimeoutExpired))
    command = '"' + sys.executable.replace("\\", "/") + '" -u sleeper.py'
    try:
        with pytest.raises(KeyboardInterrupt, match="user cancelled"):
            runner._run_phase_command("test", command, tmp_path, 30)
        assert child is not None
        deadline = time.monotonic() + 3
        while child.is_running() and child.status() != psutil.STATUS_ZOMBIE and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not child.is_running() or child.status() == psutil.STATUS_ZOMBIE, "cancelled verification kept running"
    finally:
        for proc in processes:
            if proc.poll() is None:
                kill_process_tree(proc.pid)
                proc.wait(timeout=5)
        if child is not None and child.is_running():
            kill_process_tree(child.pid)
