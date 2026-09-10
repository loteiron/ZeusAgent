"""A source install must validate its toolchain before installing Python packages."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

import zeus_cli.npm_engine as npm_engine
import zeus_constants


@pytest.fixture
def source(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "source_preflight_under_test",
        Path(__file__).resolve().parents[2] / "scripts/setup_zeus.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    root = tmp_path / "Zeus kaynak Türkçe & space"
    (root / "zeus_cli").mkdir(parents=True)
    (root / "zeus_cli/main.py").touch()
    (root / "package.json").write_text(json.dumps({
        "engines": {"node": "^22.22.0 || ^24.11.0 || >=26.0.0", "npm": "<11.10.0 || >=11.17.0"},
    }), encoding="utf-8")
    state = tmp_path / "existing state"
    state.mkdir()
    marker = state / "config.yaml"
    marker.write_text("model: configured-model\n", encoding="utf-8")
    monkeypatch.setattr(module, "ROOT", root)
    monkeypatch.setenv("ZEUS_HOME", str(state))
    monkeypatch.setattr(module, "uv_command", lambda state: ["test-uv"])
    return module, root, state, marker


@pytest.mark.parametrize("condition", ["repaired", "unrepaired", "still-incompatible", "missing", "timeout", "broken-package", "invalid-response", "probe-failed"])
def test_frontend_preflight_precedes_python_and_preserves_existing_state(source, monkeypatch, capsys, condition):
    module, root, state, marker = source
    monkeypatch.setattr(sys, "argv", ["setup_zeus.py", "--web"])
    monkeypatch.setattr(module.shutil, "which", lambda name, **kw: None if condition == "missing" else "system-npm")
    monkeypatch.setattr(module, "npm_command", lambda npm, env: ["/test/node", f"/test/{npm}/bin/npm-cli.js"])
    if condition == "broken-package":
        (root / "package.json").write_text("[]", encoding="utf-8")
    calls = []
    repairs = []

    def child(argv, **kw):
        calls.append((argv, kw))
        if "--eval" in argv:
            assert json.loads(argv[-1]) == json.loads((root / "package.json").read_text())["engines"]
            if condition == "timeout":
                raise subprocess.TimeoutExpired(argv, 15)
            if condition == "invalid-response":
                return subprocess.CompletedProcess(argv, 0, '[]', '')
            if condition == "probe-failed":
                return subprocess.CompletedProcess(argv, 1, '', 'Cannot load semver')
            compatible = "managed-npm" in argv[-2] and condition != "still-incompatible"
            return subprocess.CompletedProcess(argv, 0, json.dumps({
                "node": "24.14.1", "npm": "11.17.0" if compatible else "11.11.0", "compatible": compatible,
            }), "")
        return subprocess.CompletedProcess(argv, 0, "", "")

    def repair(npm, output, **kw):
        assert "EBADENGINE" in output
        assert not any("sync" in argv for argv, _ in calls)
        repairs.append(npm)
        return "managed-npm" if condition in {"repaired", "still-incompatible"} else None

    monkeypatch.setattr(module.subprocess, "run", child)
    monkeypatch.setattr(npm_engine, "maybe_repair_npm_engine", repair)
    if condition == "repaired":
        assert module.main() == 0
        assert repairs == ["system-npm"]
        sync = next(i for i, (argv, _) in enumerate(calls) if "sync" in argv)
        assert sum("--eval" in argv for argv, _ in calls[:sync]) == 2
        assert all(argv[:2] == ["/test/node", "/test/managed-npm/bin/npm-cli.js"] for argv, _ in calls[sync + 1:])
    else:
        with pytest.raises(SystemExit) as exc:
            module.main()
        assert exc.value.code != 0
        assert not any("sync" in argv or "ci" in argv for argv, _ in calls)
        assert not (state / "venvs").exists()
        assert "ZeusAgent ready" not in capsys.readouterr().out
    assert marker.read_text(encoding="utf-8") == "model: configured-model\n"


@pytest.mark.parametrize("compatible", [True, False])
def test_check_uses_real_npm_engine_rules_offline_without_changing_source(source, monkeypatch, compatible):
    module, root, state, _ = source
    npm = zeus_constants.find_node_executable_on_path("npm")
    assert npm, "The source-preflight test lane requires Node.js and npm."
    command = module.npm_command(npm, zeus_constants.with_zeus_node_path())
    version = json.loads((Path(command[1]).parent.parent / "package.json").read_text())["version"]
    package = root / "package.json"
    package.write_text(json.dumps({"engines": {"node": "*", "npm": version if compatible else f"<{version} || >{version}"}}), encoding="utf-8")
    before = package.read_bytes()
    monkeypatch.setattr(sys, "argv", ["setup_zeus.py", "--web", "--check"])
    monkeypatch.setenv("npm_config_force", "true")  # A global override must not hide an incompatible engine.
    monkeypatch.setenv("npm_config_engine_strict", "false")
    monkeypatch.setattr(npm_engine, "maybe_repair_npm_engine", lambda *a, **k: pytest.fail("--check must not install a runtime"))
    if compatible:
        assert module.main() == 0
    else:
        with pytest.raises(SystemExit) as exc:
            module.main()
        assert exc.value.code != 0
    assert package.read_bytes() == before
    assert not (root / "package-lock.json").exists()
    assert not (root / "node_modules").exists()
    assert not (state / "venvs").exists()
