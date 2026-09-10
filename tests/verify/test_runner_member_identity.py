"""Teardown tracks member identities across transient kernel lookup failures."""

import signal
from types import SimpleNamespace

import psutil
import pytest

from agent.verify import runner


@pytest.mark.parametrize("signal_missing", [False, True])
def test_group_lookup_disappearing_does_not_skip_a_live_member(monkeypatch, signal_missing):
    state = {"signalled": False, "sleep_count": 0, "observed_before_signal": False}

    class Member:
        def __init__(self, pid):
            self.pid = pid
            if not state["signalled"]:
                state["observed_before_signal"] = True

        def is_running(self):
            return True

        def status(self):
            return psutil.STATUS_SLEEPING if state["sleep_count"] < 2 else psutil.STATUS_ZOMBIE

    def group(pid):
        if state["signalled"]:
            raise ProcessLookupError("PID lookup vanished during exit")
        return 101

    def deliver(pgid, sig):
        assert pgid == 101 and sig == signal.SIGTERM
        state["signalled"] = True
        if signal_missing:
            raise ProcessLookupError("signal lookup vanished while the member was exiting")

    def advance(_seconds):
        state["sleep_count"] += 1

    monkeypatch.setattr(runner, "os", SimpleNamespace(name="posix", getpgid=group, killpg=deliver))
    monkeypatch.setattr(runner, "time", SimpleNamespace(monotonic=lambda: state["sleep_count"] * 0.02, sleep=advance))
    monkeypatch.setattr(psutil, "pids", lambda: [202])
    monkeypatch.setattr(psutil, "Process", Member)

    runner._terminate_process_group(SimpleNamespace(pid=101, poll=lambda: -15))

    assert state["observed_before_signal"], "ownership must be established before exit hides the PID"
    assert state["sleep_count"] == 2, "the live member must reach actual exit before teardown returns"


def test_shutdown_discovers_members_created_after_the_initial_signal(monkeypatch):
    state = {"signalled": False, "sleeps": 0, "observed": set()}

    class Member:
        def __init__(self, pid):
            self.pid = pid
            state["observed"].add(pid)

        def is_running(self):
            return True

        def status(self):
            if self.pid == 202 or state["sleeps"] == 2:
                return psutil.STATUS_ZOMBIE
            return psutil.STATUS_SLEEPING

    def deliver(_pgid, _sig):
        state["signalled"] = True

    def advance(_seconds):
        state["sleeps"] += 1

    monkeypatch.setattr(runner, "os", SimpleNamespace(name="posix", getpgid=lambda _pid: 101, killpg=deliver))
    monkeypatch.setattr(runner, "time", SimpleNamespace(monotonic=lambda: state["sleeps"] * 0.02, sleep=advance))
    monkeypatch.setattr(psutil, "pids", lambda: [202, 303] if state["signalled"] else [202])
    monkeypatch.setattr(psutil, "Process", Member)

    runner._terminate_process_group(SimpleNamespace(pid=101, poll=lambda: -15))

    assert 303 in state["observed"]
    assert state["sleeps"] == 2, "a child created during grace must also finish exiting"

def test_reused_member_pid_does_not_wait_for_an_unrelated_process(monkeypatch):
    state = {"signalled": False}

    class Member:
        def __init__(self, pid):
            self.pid = pid

        def is_running(self):
            return not state["signalled"]  # The retained PID now belongs to a different process identity.

        def status(self):
            assert not state["signalled"], "must not inspect the unrelated replacement as an owned member"
            return psutil.STATUS_SLEEPING

    def deliver(_pgid, _sig):
        state["signalled"] = True

    def unexpected_wait(_seconds):
        raise AssertionError("teardown waited for an unrelated reused PID")

    monkeypatch.setattr(runner, "os", SimpleNamespace(name="posix", getpgid=lambda _pid: 101, killpg=deliver))
    monkeypatch.setattr(runner, "time", SimpleNamespace(monotonic=lambda: 0, sleep=unexpected_wait))
    monkeypatch.setattr(psutil, "pids", lambda: [202])
    monkeypatch.setattr(psutil, "Process", Member)

    runner._terminate_process_group(SimpleNamespace(pid=101, poll=lambda: -15))


def test_an_initially_unobservable_pid_must_still_belong_to_the_owned_group(monkeypatch):
    state = {"signalled": False, "constructs": 0}

    class Replacement:
        def is_running(self):
            return True

        def status(self):
            raise AssertionError("an unrelated replacement was adopted after access became available")

    def process(pid):
        state["constructs"] += 1
        if state["constructs"] == 1:
            raise psutil.AccessDenied(pid)
        return Replacement()

    def deliver(pgid, sig):
        assert pgid == 101 and sig == signal.SIGTERM
        state["signalled"] = True

    def unexpected_wait(_seconds):
        raise AssertionError("teardown waited for the unrelated replacement")

    monkeypatch.setattr(runner, "os", SimpleNamespace(
        name="posix", getpgid=lambda _pid: 505 if state["signalled"] else 101, killpg=deliver,
    ))
    monkeypatch.setattr(runner, "time", SimpleNamespace(monotonic=lambda: 0, sleep=unexpected_wait))
    monkeypatch.setattr(psutil, "pids", lambda: [202])
    monkeypatch.setattr(psutil, "Process", process)

    runner._terminate_process_group(SimpleNamespace(pid=101, poll=lambda: -15))

    assert state["constructs"] == 2
