"""Regression tests for local terminal initial cwd normalization."""

import os

from tools.environments.local import LocalEnvironment, _resolve_local_initial_cwd


def test_relative_initial_cwd_resolves_from_parent(tmp_path, monkeypatch):
    project = tmp_path / "zeus-agent"
    project.mkdir()
    monkeypatch.chdir(tmp_path)

    assert _resolve_local_initial_cwd("zeus-agent") == str(project)


def test_local_environment_keeps_existing_relative_child_cwd(tmp_path, monkeypatch):
    project = tmp_path / "zeus-agent"
    project.mkdir()
    monkeypatch.chdir(tmp_path)

    env = LocalEnvironment(cwd="zeus-agent", timeout=5)
    try:
        result = env.execute("pwd -W" if os.name == "nt" else "pwd", timeout=5)
    finally:
        env.cleanup()

    assert result["returncode"] == 0
    assert os.path.realpath(result["output"].strip()) == os.path.realpath(project)
