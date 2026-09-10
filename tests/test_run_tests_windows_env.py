"""Native Windows location expansion survives the canonical clean test environment."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

pytestmark = pytest.mark.windows_only


def test_windows_system_locations_do_not_expand_into_relative_cache_paths(tmp_path):
    powershell = shutil.which("powershell.exe")
    assert powershell
    probe = tmp_path / "locations.ps1"
    probe.write_text(
        "@{ drive = [Environment]::ExpandEnvironmentVariables('%SystemDrive%'); "
        "data = [Environment]::ExpandEnvironmentVariables('%ProgramData%') } | ConvertTo-Json -Compress\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(probe)],
        cwd=tmp_path, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    locations = json.loads(result.stdout)
    assert locations["drive"] == Path(os.environ["SystemRoot"]).drive
    assert "%" not in locations["data"]
    assert Path(locations["data"]).is_absolute()
