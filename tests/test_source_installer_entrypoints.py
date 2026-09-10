"""Only the explicit read-only manifest is supported when sourcing legacy Bash."""
import os
from pathlib import Path
import subprocess

import pytest


INSTALLER = Path(__file__).resolve().parents[1] / "scripts/install.sh"


@pytest.mark.parametrize("arguments", [["--manifest", "--stage", "node-deps"], ["--manifest", "--ensure-deps", "node"]])
def test_sourcing_with_operational_options_refuses_before_any_install(tmp_path, arguments):
    # The manifest flag keeps the old implementation read-only even in the red
    # run; accepting extra operational flags is the missing entrypoint boundary.
    result = subprocess.run(
        ["bash", "-c", 'source "$1" "${@:2}"; result=$?; printf "caller-survived\\n"; exit "$result"',
         "source-installer-test", str(INSTALLER), *arguments],
        cwd=tmp_path, env=os.environ | {"ZEUS_HOME": str(tmp_path / "state")},
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 2
    assert "scripts/setup_zeus.py" in result.stderr
    assert "caller-survived" in result.stdout
    assert not (tmp_path / "state").exists()
