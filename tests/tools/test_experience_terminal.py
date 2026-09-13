"""Real terminal-result boundaries carry bounded experience without extra model turns."""
import json
import subprocess


def test_repeat_failure_recalls_the_prior_explanation_in_the_tool_result(tmp_path, monkeypatch):
    from agent.experience_store import ExperienceStore
    from agent.verification_evidence import begin_verification
    from tools.terminal_tool_result import _verification_evidence

    monkeypatch.setenv("ZEUS_HOME", str(tmp_path / "private"))
    root = tmp_path / "project"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")

    def failure():
        before = begin_verification(command="pytest", cwd=root, session_id="session")
        return _verification_evidence("pytest", root, "session", 1, "AssertionError: wrong timeout", before)

    first = failure()
    case_id = first["experience"]["id"]
    ExperienceStore().explain(case_id, root=root, cause="Retry delay is shorter than the worker deadline",
                             resolution="Align the two deadlines", avoid="Repeating the same check without a change")
    failure()
    result = failure()["experience"]
    assert result["same_source_failures"] == 3
    assert "deadline" in json.dumps(result["recall"])
    assert len(json.dumps(result)) <= 3500
    assert result["trust"] == "historical_data"
    assert _verification_evidence("echo hello", root, "session", 0, "hello") is None
