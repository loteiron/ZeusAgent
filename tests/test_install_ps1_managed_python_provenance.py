"""The source fork refuses legacy PowerShell installation before changing state.

The upstream managed-Python stage contracts no longer apply: source packages
install through scripts/setup_zeus.py, while install.ps1 remains disabled.
"""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest


pytestmark = pytest.mark.windows_only

_INSTALL_PS1 = Path(__file__).resolve().parents[1] / "scripts" / "install.ps1"


def _tree_contents(root: Path) -> dict[str, bytes | None]:
    return {
        path.relative_to(root).as_posix(): None if path.is_dir() else path.read_bytes()
        for path in root.rglob("*")
    }


@pytest.mark.parametrize("request_args", [("-Manifest",), ("-Stage", "venv")])
def test_source_installer_refuses_legacy_requests_without_changing_existing_state(
    tmp_path: Path, request_args: tuple[str, ...],
) -> None:
    powershell = shutil.which("powershell.exe")
    assert powershell, "Windows PowerShell is required for this native contract"

    zeus_home = tmp_path / "Zeus veri"
    install_dir = tmp_path / "existing install"
    python_path = install_dir / "venv" / "Scripts" / "python.exe"
    python_path.parent.mkdir(parents=True)
    python_path.write_bytes(b"existing environment\x00\r\n")
    (install_dir / "venv" / "empty directory").mkdir()
    zeus_home.mkdir()
    (zeus_home / "config.yaml").write_bytes(b"model: existing-model\r\n")
    before = _tree_contents(tmp_path)

    result = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(_INSTALL_PS1),
            *request_args,
            "-ZeusAgentHome",
            str(zeus_home),
            "-InstallDir",
            str(install_dir),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=45,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )

    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "scripts/setup_zeus.py --web" in output
    assert _tree_contents(tmp_path) == before
