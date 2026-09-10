"""Importing CLI helpers must not consume an embedding application's argv."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
PROBE = """
import json, os, sys
sys.argv = json.loads(sys.argv[1])
import zeus_cli.main
from zeus_cli.config import get_zeus_home
print('IMPORT_RESULT=' + json.dumps({
    'argv': sys.argv, 'home': os.environ['ZEUS_HOME'],
    'config_home': str(get_zeus_home()),
}))
"""


def _environment(tmp_path):
    state = tmp_path / "state"
    (state / "profiles" / "coder").mkdir(parents=True)
    return state, {**os.environ, "ZEUS_HOME": str(state)}


def _probe(argv, env):
    result = subprocess.run(
        [sys.executable, "-c", PROBE, json.dumps(argv)], cwd=ROOT, env=env,
        text=True, encoding="utf-8", capture_output=True, timeout=45,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    rows = [line for line in result.stdout.splitlines() if line.startswith("IMPORT_RESULT=")]
    assert rows, result.stdout + result.stderr
    return json.loads(rows[-1].partition("=")[2])


@pytest.mark.parametrize("flags", [
    ["-p", "foreign_plugin"], ["-p", "coder"], ["--profile=coder"], ["--version"], ["-V"],
])
def test_foreign_argv_survives_cli_import(tmp_path, flags):
    state, env = _environment(tmp_path)
    argv = ["embedding-host", *flags]
    assert _probe(argv, env) == {"argv": argv, "home": str(state), "config_home": str(state)}


@pytest.mark.parametrize("entry", ["zeus", "zeus.exe", "zeus-script.py", "module", "wrapper"])
def test_cli_profile_is_resolved_before_configuration_import(tmp_path, entry):
    state, env = _environment(tmp_path)
    if entry in {"module", "wrapper"}:
        command = ["-m", "zeus_cli.main"] if entry == "module" else [str(ROOT / "zeus")]
        result = subprocess.run(
            [sys.executable, *command, "-p", "coder", "--help"], cwd=ROOT, env=env,
            text=True, encoding="utf-8", capture_output=True, timeout=45,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "usage:" in result.stdout.lower()
        assert (state / "profiles" / "coder" / "logs").is_dir()
        assert not (state / "logs").exists()
    else:
        expected = str(state / "profiles" / "coder")
        assert _probe([entry, "chat", "-p", "coder"], env) == {
            "argv": [entry, "chat"], "home": expected, "config_home": expected,
        }
