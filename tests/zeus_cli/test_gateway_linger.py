"""Tests for gateway linger auto-enable behavior on headless Linux installs."""

from types import SimpleNamespace

import pytest

import zeus_cli.gateway as gateway


class TestEnsureLingerEnabled:
    def test_linger_already_enabled_via_file(self, monkeypatch, capsys):
        monkeypatch.setattr(gateway, "is_linux", lambda: True)
        monkeypatch.setattr(gateway, "is_termux", lambda: False)
        monkeypatch.setattr("getpass.getuser", lambda: "testuser")
        monkeypatch.setattr(gateway, "Path", lambda _path: SimpleNamespace(exists=lambda: True))

        calls = []
        monkeypatch.setattr(gateway.subprocess, "run", lambda *args, **kwargs: calls.append((args, kwargs)))

        gateway._ensure_linger_enabled()

        out = capsys.readouterr().out
        assert "Systemd linger is enabled" in out
        assert calls == []


    def test_loginctl_success_enables_linger(self, monkeypatch, capsys):
        monkeypatch.setattr(gateway, "is_linux", lambda: True)
        monkeypatch.setattr(gateway, "is_termux", lambda: False)
        monkeypatch.setattr("getpass.getuser", lambda: "testuser")
        monkeypatch.setattr(gateway, "Path", lambda _path: SimpleNamespace(exists=lambda: False))
        monkeypatch.setattr(gateway, "get_systemd_linger_status", lambda: (False, ""))
        monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/loginctl")

        run_calls = []

        def fake_run(cmd, capture_output=False, text=False, check=False, **kwargs):
            run_calls.append((cmd, capture_output, text, check))
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        monkeypatch.setattr(gateway.subprocess, "run", fake_run)

        gateway._ensure_linger_enabled()

        out = capsys.readouterr().out
        assert "Enabling linger" in out
        assert "Linger enabled" in out
        assert run_calls == [(["loginctl", "enable-linger", "testuser"], True, True, False)]


    def test_loginctl_failure_shows_manual_guidance(self, monkeypatch, capsys):
        monkeypatch.setattr(gateway, "is_linux", lambda: True)
        monkeypatch.setattr(gateway, "is_termux", lambda: False)
        monkeypatch.setattr("getpass.getuser", lambda: "testuser")
        monkeypatch.setattr(gateway, "Path", lambda _path: SimpleNamespace(exists=lambda: False))
        monkeypatch.setattr(gateway, "get_systemd_linger_status", lambda: (False, ""))
        monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/loginctl")
        monkeypatch.setattr(
            gateway.subprocess,
            "run",
            lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="", stderr="Permission denied"),
        )

        gateway._ensure_linger_enabled()

        out = capsys.readouterr().out
        assert "sudo loginctl enable-linger testuser" in out
        assert "Permission denied" in out


def test_systemd_install_calls_linger_helper(monkeypatch, tmp_path, capsys):
    unit_path = tmp_path / "systemd" / "user" / "zeus-gateway.service"

    monkeypatch.setattr(gateway, "get_systemd_unit_path", lambda system=False: unit_path)
    # Non-temp home so the temp-home write guard (which trips on the
    # hermetic test ZEUS_HOME) stays out of the way.
    monkeypatch.setattr(
        gateway,
        "generate_systemd_unit",
        lambda system=False, run_as_user=None: (
            '[Service]\nEnvironment="ZEUS_HOME=/home/alice/.zeus"\n'
        ),
    )

    calls = []

    def fake_run(cmd, check=False, **kwargs):
        calls.append((cmd, check))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    helper_calls = []
    monkeypatch.setattr(gateway.subprocess, "run", fake_run)
    monkeypatch.setattr(gateway, "_ensure_linger_enabled", lambda: helper_calls.append(True))

    gateway.systemd_install(force=False)

    out = capsys.readouterr().out
    assert unit_path.exists()
    assert [cmd for cmd, _ in calls] == [
        ["systemctl", "--user", "daemon-reload"],
        ["systemctl", "--user", "enable", gateway.get_service_name()],
    ]
    assert helper_calls == [True]
    assert "User service installed and enabled" in out


@pytest.mark.parametrize("system", [False, True])
def test_systemd_install_repair_path_keeps_linger_guarantee(monkeypatch, tmp_path, system):
    """Repairing a stale unit used to return before the linger step, so an upgraded headless
    user service died at logout (#12863). System scope never touches user linger."""
    unit_path = tmp_path / "zeus-gateway.service"
    unit_path.write_text("old unit\n", encoding="utf-8")
    monkeypatch.setattr(gateway, "get_systemd_unit_path", lambda system=False: unit_path)
    monkeypatch.setattr(gateway, "systemd_unit_is_current", lambda system=False: False)
    monkeypatch.setattr(gateway, "has_legacy_zeus_units", lambda: False)
    monkeypatch.setattr(gateway, "_require_root_for_system_service", lambda _action: None)
    monkeypatch.setattr(gateway, "_sync_zeus_home_from_systemd_unit", lambda system=False: None)
    monkeypatch.setattr(gateway, "_read_systemd_user_from_unit", lambda path: None)
    monkeypatch.setattr(gateway, "refresh_systemd_unit_if_needed", lambda system=False: None)
    monkeypatch.setattr(gateway, "_run_systemctl", lambda *args, **kwargs: None)
    helper_calls = []
    monkeypatch.setattr(gateway, "_ensure_linger_enabled", lambda: helper_calls.append(True))

    gateway.systemd_install(force=False, system=system)

    assert helper_calls == ([] if system else [True])
