"""Packaged runtimes never enter the mutable source / upstream ZIP updater."""
from argparse import Namespace

import pytest

from zeus_cli.update_contract import evaluate_update_admission


@pytest.mark.parametrize("contents,expected", [
    ('{"schemaVersion":1,"manager":"zeus-windows-release"}', "zeus-windows-release"),
    ('{"schemaVersion":1,"manager":"zeus-linux-release"}', "zeus-linux-release"),
    ("corrupt {", "zeus-packaged-release"), ("", "zeus-packaged-release"),
    ('{"manager":"git"}', "zeus-packaged-release"),
])
def test_release_marker_refuses_before_mutable_install_heuristics(tmp_path, monkeypatch, contents, expected):
    (tmp_path / ".zeus-runtime.json").write_text(contents, encoding="utf-8")
    def unexpected(*args, **kwargs):
        pytest.fail("A packaged runtime must never enter mutable install detection")
    monkeypatch.setattr("zeus_cli.config.detect_install_method", unexpected)
    refusal = evaluate_update_admission(tmp_path)
    assert refusal is not None
    assert refusal.code == expected
    assert "loteiron/ZeusAgent/releases" in refusal.message
    assert "NousResearch" not in refusal.message
    if expected == "zeus-linux-release":
        assert "Linux" in refusal.message and ".deb" in refusal.message
        assert "Windows" not in refusal.message


def test_non_regular_marker_is_still_immutable_without_opening_it(tmp_path, monkeypatch):
    marker = tmp_path / ".zeus-runtime.json"
    marker.mkdir()
    refusal = evaluate_update_admission(tmp_path)
    assert refusal.code == "zeus-packaged-release"


@pytest.mark.parametrize("check", [False, True])
def test_release_cli_update_stops_before_git_network_or_dependency_changes(tmp_path, monkeypatch, capsys, check):
    from zeus_cli import main
    (tmp_path / ".zeus-runtime.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("ZEUS_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(main, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("zeus_cli.config.is_managed", lambda: False)
    monkeypatch.setattr("zeus_cli.update_contract.record_refusal_receipt", lambda refusal: None)
    def unexpected(*args, **kwargs):
        pytest.fail("Packaged update started the source updater")
    monkeypatch.setattr("zeus_cli.update_cmd._cmd_update_impl", unexpected)
    monkeypatch.setattr("zeus_cli.update_cmd._cmd_update_check", unexpected)
    with pytest.raises(SystemExit) as stopped:
        main.cmd_update(Namespace(check=check, plan=False))
    assert stopped.value.code == 2
    assert "Zeus" in capsys.readouterr().out


@pytest.mark.parametrize("contents", ["{}", "corrupt {"])
def test_release_update_plan_matches_shared_admission_without_mutation(tmp_path, monkeypatch, capsys, contents):
    from zeus_cli.update_inventory import UpdatePlan, _collect_install_shape, print_update_plan
    project = tmp_path / "packaged-runtime"
    project.mkdir()
    marker = project / ".zeus-runtime.json"
    marker.write_text(contents, encoding="utf-8")
    monkeypatch.setattr("zeus_cli.config.get_project_root", lambda: project)
    monkeypatch.setattr("zeus_cli.config.get_managed_system", lambda: None)
    plan = UpdatePlan()
    _collect_install_shape(plan)
    refusal = evaluate_update_admission(project)
    assert plan.updatable_in_place is False
    assert plan.install_method == refusal.code
    assert plan.update_mechanism == refusal.update_command
    print_update_plan(plan)
    assert "NOT updatable in place" in capsys.readouterr().out
    assert list(project.iterdir()) == [marker]
    assert marker.read_text() == contents
