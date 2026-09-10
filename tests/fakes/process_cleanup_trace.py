"""Native process and socket observations scoped to the owned test server."""

import json
import os
from pathlib import Path
import platform
import socket
import time
import uuid

import psutil

from agent.verify import runner


class ProcessCleanupTrace:
    def __init__(self, monkeypatch, tmp_path, port, name):
        self.started = time.monotonic()
        self.tmp_path, self.port, self.name = tmp_path, port, name
        self.events, self.owned = [], set()
        self.first_connect = None
        self.group = None
        self.getpgid = getattr(os, "getpgid", None)
        self.status, self.pids = psutil.Process.status, psutil.pids
        if os.name == "nt":
            return
        self.terminate, self.signal = runner._terminate_process_group, os.killpg
        monkeypatch.setattr(os, "getpgid", self.observe_group)
        monkeypatch.setattr(psutil.Process, "status", lambda process: self.observe_status(process))
        monkeypatch.setattr(psutil, "pids", self.observe_pids)
        monkeypatch.setattr(os, "killpg", self.observe_signal)
        monkeypatch.setattr(runner, "_terminate_process_group", self.observe_terminate)

    def record(self, event, **values):
        row = {"event": event, **values}
        if not self.events or {key: value for key, value in self.events[-1].items() if key != "elapsed"} != row:
            self.events.append({"elapsed": round(time.monotonic() - self.started, 6), **row})

    def snapshot(self, label):
        rows = []
        listed = self.pids()
        for pid in sorted(self.owned):
            row = {"pid": pid, "listed": pid in listed}
            try:
                row["pgid"] = self.getpgid(pid)
            except OSError as exc:
                row["group_error"] = repr(exc)
            try:
                row["status"] = self.status(psutil.Process(pid))
            except psutil.Error as exc:
                row["status_error"] = repr(exc)
            rows.append(row)
        self.record(label, members=rows)

    def observe_pids(self):
        result = self.pids()
        self.record("listed_owned", pids=sorted(self.owned.intersection(result)))
        return result

    def observe_group(self, pid):
        try:
            result = self.getpgid(pid)
        except OSError as exc:
            if pid in self.owned:
                self.record("getpgid_error", pid=pid, error=repr(exc))
            raise
        if pid in self.owned:
            self.record("getpgid", pid=pid, group=result)
        return result

    def observe_status(self, process):
        try:
            result = self.status(process)
        except psutil.Error as exc:
            if process.pid in self.owned:
                self.record("status_error", pid=process.pid, error=repr(exc))
            raise
        if process.pid in self.owned:
            self.record("status", pid=process.pid, status=result)
        return result

    def observe_signal(self, pgid, sig):
        self.record("signal", group=pgid, signal=int(sig))
        try:
            return self.signal(pgid, sig)
        except OSError as exc:
            self.record("signal_error", group=pgid, signal=int(sig), error=repr(exc))
            raise

    def connect(self):
        with socket.socket() as probe:
            probe.settimeout(0.5)
            result = probe.connect_ex(("127.0.0.1", self.port))
            # A closed ephemeral destination can equal the OS-selected source
            # port. Record both ends to distinguish TCP self-connect from a
            # surviving listener without adding a second request.
            self.record("socket", result=result, local=probe.getsockname(),
                        peer=probe.getpeername() if result == 0 else None)
            return result

    def observe_terminate(self, proc):
        self.group = proc.pid
        self.owned.add(proc.pid)
        try:
            self.owned.add(int((self.tmp_path / "child.pid").read_text(encoding="utf-8")))
        except FileNotFoundError:
            self.record("child_not_started")
        self.snapshot("before_terminate")
        try:
            self.terminate(proc)
        finally:
            # Observe the original failure BEFORE psutil inspection can give an
            # exiting child extra time to release its listener. Assert this
            # stored result even if later diagnostic sampling finds it closed.
            self.first_connect = self.connect()
            self.record("first_connect_after_terminate", result=self.first_connect)
            self.snapshot("after_terminate")
            self.record("leader", pid=proc.pid, exit_code=proc.poll())
            if self.first_connect == 0:
                for pause in (0.01, 0.05, 0.2):
                    time.sleep(pause)
                    self.record("later_connect", pause=pause, result=self.connect())
                    self.snapshot("later_members")

    def assert_stopped(self):
        assert self.first_connect != 0, "cleanup returned with its server listening: " + json.dumps(self.events)

    def finish(self):
        if os.name == "nt":
            return
        # The canonical runner intentionally removes ambient CI variables.
        # Keep observations in an ignored, known location for artifact upload.
        directory = Path(__file__).resolve().parents[2] / ".pytest_cache" / "zeus-cleanup-diagnostics"
        directory.mkdir(parents=True, exist_ok=True)
        destination = directory / f"{self.name}-{os.getpid()}-{uuid.uuid4().hex[:8]}.json"
        destination.write_text(json.dumps({
            "platform": platform.platform(), "python": platform.python_version(),
            "psutil": psutil.__version__, "port": self.port,
            "first_connect": self.first_connect, "events": self.events,
        }, indent=2), encoding="utf-8")
