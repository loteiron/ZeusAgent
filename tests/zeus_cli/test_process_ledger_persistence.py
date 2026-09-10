"""Startup records survive malformed bytes and simultaneous process registration."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from zeus_cli import process_identity as identity


@pytest.mark.parametrize("damaged", [b"\xff\xfeincomplete", b'{"incomplete":'])
def test_corrupt_process_ledger_is_preserved_and_does_not_block_registration(tmp_path, monkeypatch, damaged):
    ledger = tmp_path / "spawn-ledger.json"
    ledger.write_bytes(damaged)
    monkeypatch.setattr(identity, "_ledger_path", lambda: ledger)
    assert identity.ledger_entries(project_root=tmp_path) == []
    assert ledger.with_suffix(".json.corrupt").read_bytes() == damaged
    assert identity.register_self("serve", project_root=tmp_path)
    entries = json.loads(ledger.read_text(encoding="utf-8"))
    assert [(row["pid"], row["purpose"]) for row in entries] == [(os.getpid(), "serve")]


def test_concurrent_process_registrations_preserve_every_unresolved_owner(tmp_path):
    ledger = tmp_path / "shared ledger Türkçe.json"
    script = tmp_path / "register.py"
    script.write_text(
        "import os, sys, time\n"
        "from pathlib import Path\n"
        "from zeus_cli import process_identity as identity\n"
        "identity._ledger_path = lambda: Path(sys.argv[1])\n"
        # Unknown liveness is an existing supported state: this test isolates the
        # file transaction from host process-table availability, never fakes an OS.
        "identity._pid_alive_matches = lambda *args: None\n"
        "read = identity._read_ledger\n"
        "def delayed_read(path):\n"
        "    rows = read(path)\n"
        "    time.sleep(1)\n"
        "    return rows\n"
        "identity._read_ledger = delayed_read\n"
        "while not Path(sys.argv[2]).exists(): time.sleep(0.01)\n"
        "assert identity.register_self('serve', project_root=Path.cwd())\n"
        "print(os.getpid(), flush=True)\n",
        encoding="utf-8",
    )
    gate = tmp_path / "start"
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2]), "PYTHONUTF8": "1"}
    children = [subprocess.Popen([sys.executable, str(script), str(ledger), str(gate)], env=env,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(4)]
    gate.touch()
    results = [child.communicate(timeout=30) for child in children]
    assert all(child.returncode == 0 for child in children), results
    # Windows venv launchers spawn workers, so Popen.pid may not own the entry.
    owner_pids = {int(stdout) for stdout, _stderr in results}
    assert len(owner_pids) == len(children)
    rows = json.loads(ledger.read_text(encoding="utf-8"))
    assert {row["pid"] for row in rows} == owner_pids
