"""An unattended refresh owns its temporary script even before spawn."""

import pytest

from zeus_cli import tools_config_cua as cua


@pytest.mark.parametrize("preflight_raises", [False, True])
def test_preflight_failure_releases_downloaded_installer(tmp_path, monkeypatch, preflight_raises):
    script = tmp_path / "downloaded-installer.sh"
    script.write_text("exit 0\n", encoding="utf-8")
    unrelated = tmp_path / "keep.sh"
    unrelated.write_text("preserve me\n", encoding="utf-8")
    monkeypatch.setattr(
        cua, "_cua_installer_command",
        lambda is_windows: (["unused-installer"], "manual install", str(script)),
    )
    monkeypatch.setattr(cua, "_clear_stale_cua_install_lock", lambda: None)

    def refuse(command, is_windows):
        if preflight_raises:
            raise OSError("preflight unavailable")
        return None

    def unexpected_spawn(*args, **kwargs):
        pytest.fail("A failed preflight must never launch the installer")

    monkeypatch.setattr(cua, "_unattended_installer_preflight", refuse)
    monkeypatch.setattr(cua.subprocess, "Popen", unexpected_spawn)
    assert cua._run_cua_driver_installer(
        verbose=False, show_progress=False, installer_timeout=120,
    ) is False
    assert not script.exists()
    assert unrelated.read_text(encoding="utf-8") == "preserve me\n"
