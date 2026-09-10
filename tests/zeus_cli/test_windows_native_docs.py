from pathlib import Path


def test_windows_native_install_path_docs_match_installer() -> None:
    doc = Path("website/docs/user-guide/windows-native.md").read_text()
    install = Path("scripts/install.ps1").read_text()

    # The launchers live in the managed binary dir OUTSIDE the git checkout
    # (ZEUS_HOME\bin, next to the managed uv) — NOT the whole venv\Scripts
    # (which would shadow the user's python, #83797) and NOT a dir inside
    # the checkout (which `zeus update`'s autostash swept off disk).
    assert "%LOCALAPPDATA%\\zeus\\bin" in doc
    assert (
        "Get-Command zeus        # should print "
        "C:\\Users\\<you>\\AppData\\Local\\zeus\\bin\\zeus.exe"
    ) in doc
    # Installer exposes $ZeusAgentHome\bin, and must copy the launchers into it.
    assert '$zeusBin = "$ZeusAgentHome\\bin"' in install
    assert "zeus.exe" in install and "zeus-acp.exe" in install
    # Guard against regressions to either legacy layout.
    assert '$zeusBin = "$InstallDir\\venv\\Scripts"' not in install
    assert '$zeusBin = "$InstallDir\\bin"' not in install
