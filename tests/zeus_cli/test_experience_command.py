"""The public command owns inspection and annotation, not execution or certification."""
import argparse
import json
import subprocess
import os
from pathlib import Path
import sys


def test_command_roundtrip_reports_evidence_and_keeps_explanations_separate(tmp_path, monkeypatch, capsys):
    from zeus_cli.subcommands.experience import build_experience_parser
    from zeus_cli.experience_command import run_experience_command
    from agent.verification_evidence import begin_verify_run, record_verify_run

    monkeypatch.setenv("ZEUS_HOME", str(tmp_path / "profile"))
    root = tmp_path / "project"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / "app.py").write_text("broken = True\n", encoding="utf-8")
    before = begin_verify_run(root=root, session_id="a")
    record_verify_run(root=root, session_id="a", ok=False, output="Connection test failed", workspace_before=before)
    parser = argparse.ArgumentParser()
    build_experience_parser(parser.add_subparsers())

    def invoke(*args):
        parsed = parser.parse_args(["experience", *args, "--root", str(root), "--json"])
        code = run_experience_command(parsed)
        return code, json.loads(capsys.readouterr().out)

    code, report = invoke("list")
    assert code == 0
    case_id = report["experiences"][0]["id"]
    code, detail = invoke("explain", case_id, "--cause", "Missing timeout", "--resolution", "Set a bounded timeout")
    assert code == 0 and detail["causal_explanation"] == "hypothesis"
    assert detail["state"] == "unresolved"
    assert invoke("recall", "timeout")[1]["experiences"][0]["id"] == case_id
    assert invoke("show", case_id)[1]["observations"][0]["status"] == "failed"
    assert invoke("forget", case_id)[1]["forgotten"] is True
    assert invoke("list")[1]["experiences"] == []
    launched = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parents[2] / "zeus"), "experience", "list", "--root", str(root), "--json"],
        cwd=tmp_path, env={**os.environ, "PYTHONIOENCODING": "utf-8"}, capture_output=True, text=True, timeout=60,
    )
    assert launched.returncode == 0, launched.stderr
    assert json.loads(launched.stdout)["experiences"] == []


def test_quick_backup_carries_experiences_and_their_observations(tmp_path, monkeypatch):
    from agent.verification_evidence import begin_verify_run, record_verify_run
    from agent.experience_store import ExperienceStore
    from zeus_cli.backup import create_quick_snapshot

    home = tmp_path / "profile"
    monkeypatch.setenv("ZEUS_HOME", str(home))
    root = tmp_path / "project"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    result = record_verify_run(root=root, session_id="s", ok=False, output="Keep this observation",
                              workspace_before=begin_verify_run(root=root, session_id="s"))
    snapshot = create_quick_snapshot(zeus_home=home)
    restored_home = home / "state-snapshots" / snapshot
    monkeypatch.setenv("ZEUS_HOME", str(restored_home))
    detail = ExperienceStore().show(result["experience"]["id"], root=root)
    assert detail["symptom"] == "Keep this observation"
    assert detail["observations"][0]["event_id"] == result["id"]
