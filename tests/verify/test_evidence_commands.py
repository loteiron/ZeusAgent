"""The evidence CLI reports actual receipts without executing another recipe."""
import argparse
import json
import subprocess

from agent import verification_evidence as evidence
from agent.workspace_identity import capture_workspace
from zeus_cli.subcommands.verify import build_verify_parser
from zeus_cli.verify_cmd import run_verify_command


def parse(*args):
    parser = argparse.ArgumentParser()
    build_verify_parser(parser.add_subparsers(), cmd_verify=run_verify_command)
    return parser.parse_args(["verify", *map(str, args)])


def test_evidence_commands_share_current_results_baseline_and_session(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ZEUS_HOME", str(tmp_path / "state"))
    root = tmp_path / "project"
    root.mkdir()
    (root / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    evidence.record_terminal_result(command="pytest", cwd=root, session_id="engineering", exit_code=1,
                                    workspace_before=capture_workspace(root))
    args = [root, "--session", "engineering", "--json"]
    assert run_verify_command(parse(*args, "--status")) == 1
    assert json.loads(capsys.readouterr().out)["verification"]["status"] == "failed"
    assert run_verify_command(parse(*args, "--capture-baseline")) == 0
    baseline = json.loads(capsys.readouterr().out)["baseline"]
    assert baseline["check_count"] == 1
    evidence.record_terminal_result(command="pytest", cwd=root, session_id="engineering", exit_code=0,
                                    workspace_before=capture_workspace(root))
    assert run_verify_command(parse(*args, "--status")) == 0
    report = json.loads(capsys.readouterr().out)["verification"]
    assert report["checks"][0]["comparison"] == "fixed"
    (root / "new.py").write_text("changed", encoding="utf-8")
    assert run_verify_command(parse(*args, "--capture-baseline")) == 2
    assert "error" in json.loads(capsys.readouterr().out)
    assert evidence.verification_status(session_id="engineering", cwd=root)["baseline"]["id"] == baseline["id"]
    assert run_verify_command(parse(*args, "--clear-baseline")) == 0
    assert json.loads(capsys.readouterr().out)["cleared"] is True


def test_report_rejects_recipe_mutation_flags_and_never_saves(tmp_path, capsys):
    assert run_verify_command(parse(tmp_path, "--status", "--save", "--json")) == 2
    assert "error" in json.loads(capsys.readouterr().out)
    assert not (tmp_path / ".zeus" / "environment.json").exists()
