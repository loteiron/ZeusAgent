"""Console evidence uses the actual workspace/session ledger, without executing checks."""
from types import SimpleNamespace
import subprocess

import pytest

from agent.verification_evidence import record_terminal_result
from agent.workspace_identity import capture_workspace
from zeus_cli.cli_commands_mixin import CLICommandsMixin
from zeus_cli.commands import resolve_command


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    (root / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
    (root / "app.py").write_text("answer = 42\n", encoding="utf-8")
    subprocess.run(["git", "init", "--quiet", str(root)], check=True, capture_output=True)
    monkeypatch.setenv("ZEUS_HOME", str(tmp_path / "profile"))
    monkeypatch.chdir(root)
    return root


def _record(root, command, code, output, session="console-session"):
    before = capture_workspace(root)
    record_terminal_result(command=command, cwd=root, session_id=session, exit_code=code, output=output,
                           workspace_before=before, workspace_after=capture_workspace(root))


def _show(monkeypatch, command="/evidence", session="console-session"):
    output = []
    monkeypatch.setattr("zeus_cli.cli_commands_mixin._cp", output.append)
    CLICommandsMixin._handle_evidence_command(SimpleNamespace(session_id=session), command)
    return "\n".join(output)


def test_evidence_is_a_registered_read_only_console_command(workspace, monkeypatch):
    assert resolve_command("/evidence").name == "evidence"
    text = _show(monkeypatch, "/evidence pytest")
    assert "Usage: /evidence [status]" in text
    assert not (workspace.parent / "profile" / "verification.sqlite3").exists()


def test_console_report_keeps_failure_visible_after_an_unrelated_pass(workspace, monkeypatch):
    _record(workspace, "pytest tests/unit", 1, "assertion failed")
    _record(workspace, "pytest tests/smoke", 0, "1 passed")
    text = _show(monkeypatch)
    assert "Verification: failed" in text
    assert "FAILED | current" in text
    assert "PASSED | current" in text
    assert "pytest tests/unit" in text and "pytest tests/smoke" in text
    assert "assertion failed" in text
    assert str(workspace) in text
    assert "console-session" in text


def test_current_evidence_becomes_stale_after_real_file_edit_and_is_session_scoped(workspace, monkeypatch):
    _record(workspace, "pytest", 0, "all passed")
    assert "PASSED | current" in _show(monkeypatch)
    (workspace / "app.py").write_text("answer = 43\n", encoding="utf-8")
    text = _show(monkeypatch)
    assert "Verification: stale" in text
    assert "PASSED | stale" in text
    assert "No recorded checks" in _show(monkeypatch, session="other-session")
