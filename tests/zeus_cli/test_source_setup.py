"""Source setup must use locked dependencies and stop at the first failed stage."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest
import zeus_constants


_SPEC = importlib.util.spec_from_file_location(
    "source_setup", Path(__file__).resolve().parents[2] / "scripts/setup_zeus.py"
)
assert _SPEC and _SPEC.loader
setup = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(setup)


@pytest.fixture
def commands(tmp_path, monkeypatch):
    root = tmp_path / "source tree"
    (root / "zeus_cli").mkdir(parents=True)
    (root / "zeus_cli/main.py").touch()
    (root / "package.json").write_text(json.dumps({"engines": {"node": "*", "npm": "*"}}), encoding="utf-8")
    monkeypatch.setattr(setup, "ROOT", root)
    monkeypatch.setattr(zeus_constants, "get_zeus_home", lambda: tmp_path / "private state")
    monkeypatch.setattr(setup, "uv_command", lambda state: ["test-uv"])
    monkeypatch.setattr(setup.shutil, "which", lambda name, **kw: "test-npm" if name == "npm" else None)
    monkeypatch.setattr(setup, "npm_command", lambda npm, env: ["/test/node", "/test/npm/bin/npm-cli.js"])
    observed = []

    def run(argv, **kwargs):
        observed.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, json.dumps({"node": "24.14.1", "npm": "11.17.0", "compatible": True}), "")

    monkeypatch.setattr(setup.subprocess, "run", run)
    return observed


def test_complete_test_setup_is_locked_and_does_not_install_frontends(commands, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["setup_zeus.py", "--test-all"])
    assert setup.main() == 0
    assert len(commands) == 1
    argv, options = commands[0]
    extras = {argv[i + 1] for i, value in enumerate(argv) if value == "--extra"}
    assert {"all", "dev", "anthropic", "mistral", "fal", "modal", "daytona", "hindsight", "parallel-web", "messaging", "wecom"} <= extras
    assert "--locked" in argv and "--python" in argv
    assert options["check"] is True
    assert Path(options["env"]["UV_PROJECT_ENVIRONMENT"]).name == "zeus-agent"


@pytest.mark.parametrize("failed_stage", ["sync", "ci", "build"])
def test_failed_setup_never_runs_later_stages(commands, monkeypatch, capsys, failed_stage):
    monkeypatch.setattr(sys, "argv", ["setup_zeus.py", "--desktop"])
    original = setup.subprocess.run

    def fail(argv, **kwargs):
        result = original(argv, **kwargs)
        if failed_stage in argv:
            raise subprocess.CalledProcessError(23, argv)
        return result

    monkeypatch.setattr(setup.subprocess, "run", fail)
    with pytest.raises(subprocess.CalledProcessError) as error:
        setup.main()
    assert error.value.returncode == 23
    assert len(commands) == {"sync": 2, "ci": 3, "build": 4}[failed_stage]
    assert "ZeusAgent ready" not in capsys.readouterr().out


@pytest.mark.parametrize("flag", ["--web", "--desktop"])
def test_web_setup_does_not_require_desktop_native_dependencies(commands, monkeypatch, flag):
    monkeypatch.setattr(sys, "argv", ["setup_zeus.py", flag])
    assert setup.main() == 0
    install = next(argv for argv, _options in commands if "ci" in argv)
    assert "--ignore-scripts" not in install
    selected = {install[i + 1] for i, argument in enumerate(install) if argument == "--workspace"}
    if flag == "--web":
        assert selected == {"ui-tui", "web", "@zeus/ink", "@zeus/shared"}
        assert "--include-workspace-root" in install
    else:
        assert not selected  # Desktop setup needs the complete locked workspace.
