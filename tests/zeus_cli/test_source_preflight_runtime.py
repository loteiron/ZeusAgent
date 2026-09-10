"""Prerequisite checks must work even when starting npm itself would fail or stall."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "source_runtime_under_test", Path(__file__).resolve().parents[2] / "scripts/setup_zeus.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    node = shutil.which("node")
    npm = shutil.which("npm")
    assert node and npm, "This test lane requires a real Node.js/npm installation."
    installed = Path(npm).resolve()
    candidates = [installed.parent.parent / "package.json",
                  installed.parent / "node_modules/npm/package.json",
                  installed.parent.parent / "lib/node_modules/npm/package.json"]
    npm_package = next(p for p in candidates if p.is_file() and json.loads(p.read_text())["name"] == "npm")
    semver = subprocess.run(
        [node, "--eval", "console.log(require.resolve('semver/package.json', {paths: [process.argv[1]]}))", str(npm_package.parent)],
        check=True, capture_output=True, text=True, timeout=15,
    ).stdout.strip()
    root = tmp_path / "Zeus kaynak Türkçe & space"
    (root / "zeus_cli").mkdir(parents=True)
    (root / "zeus_cli/main.py").touch()
    state = tmp_path / "existing state"
    state.mkdir()
    (state / "config.yaml").write_text("model: retained\n")
    monkeypatch.setattr(module, "ROOT", root)
    monkeypatch.setenv("ZEUS_HOME", str(state))
    marker = tmp_path / "npm-started"

    def make(version, layout, engines):
        prefix = tmp_path / "Node araçları & spaces"
        package = prefix / ("node_modules/npm" if layout == "prefix" else "lib/node_modules/npm")
        (package / "bin").mkdir(parents=True)
        (package / "package.json").write_text(json.dumps({"name": "npm", "version": version}), encoding="utf-8")
        shutil.copytree(Path(semver).parent, package / "node_modules/semver")
        cli = package / "bin/npm-cli.js"
        cli.write_text("#!/usr/bin/env node\nrequire('node:fs').writeFileSync(" + json.dumps(str(marker)) + ", 'started'); process.exit(97);\n", encoding="utf-8")
        cli.chmod(0o755)
        bin_dir = prefix if layout == "prefix" else prefix / "bin"
        bin_dir.mkdir(exist_ok=True)
        launcher = bin_dir / ("npm.cmd" if os.name == "nt" else "npm")
        if os.name == "nt":
            launcher.write_text('@"' + node + '" "' + str(cli) + '" %*\n')
        elif layout == "linked":
            launcher.symlink_to(cli)
        else:
            launcher.write_bytes(cli.read_bytes())
            launcher.chmod(0o755)
        monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ["PATH"])
        (root / "package.json").write_text(json.dumps({"engines": engines}), encoding="utf-8")
        return cli

    return module, root, state, marker, node, make


@pytest.mark.parametrize("layout", ["prefix", "bin", "linked"])
@pytest.mark.parametrize("version,node_range,npm_range,expected", [
    ("11.9.0", "*", "<11.10.0 || >=11.17.0", 0),
    ("11.10.0", "*", "<11.10.0 || >=11.17.0", 2),
    ("11.11.0", "*", "<11.10.0 || >=11.17.0", 2),
    ("11.16.9", "*", "<11.10.0 || >=11.17.0", 2),
    ("11.17.0", "*", "<11.10.0 || >=11.17.0", 0),
    ("11.17.0-beta.1", "*", "<11.10.0 || >=11.17.0", 2),
    ("11.17.0", "<1.0.0", "*", 2),
    ("11.17.0", "*", "~11.17.0 || 12.x", 0),
])
def test_check_reads_installed_engines_without_starting_npm(runtime, monkeypatch, capsys, layout, version, node_range, npm_range, expected):
    module, root, state, marker, _, make = runtime
    make(version, layout, {"node": node_range, "npm": npm_range})
    before = (root / "package.json").read_bytes()
    monkeypatch.setenv("npm_config_force", "true")
    monkeypatch.setenv("npm_config_engine_strict", "false")
    monkeypatch.setenv("npm_config_registry", "http://127.0.0.1:1")
    monkeypatch.setattr(sys, "argv", ["setup_zeus.py", "--web", "--check"])
    if expected:
        with pytest.raises(SystemExit) as exc:
            module.main()
        assert exc.value.code == expected
        error = capsys.readouterr().err
        assert "EBADENGINE" in error and version in error
    else:
        assert module.main() == 0
    assert not marker.exists(), "A version check must not enter npm's launcher, config loader or installer."
    assert (root / "package.json").read_bytes() == before
    assert not (root / "package-lock.json").exists() and not (root / "node_modules").exists()
    assert {p.name for p in state.iterdir()} == {"config.yaml"}
    assert (state / "config.yaml").read_text() == "model: retained\n"


@pytest.mark.parametrize("layout", ["prefix", "bin", "linked"])
def test_install_uses_the_exact_node_and_npm_that_passed_preflight(runtime, monkeypatch, layout):
    module, _, _, marker, node, make = runtime
    cli = make("11.17.0", layout, {"node": "*", "npm": ">=11.17.0"})
    monkeypatch.setattr(sys, "argv", ["setup_zeus.py", "--web"])
    monkeypatch.setattr(module, "uv_command", lambda state: ["test-uv"])
    real_run = subprocess.run
    installs = []

    def child(argv, **kw):
        if "sync" in argv or "ci" in argv or "run" in argv:
            installs.append((argv, kw))
            return subprocess.CompletedProcess(argv, 0, "", "")
        return real_run(argv, **kw)

    monkeypatch.setattr(module.subprocess, "run", child)
    assert module.main() == 0
    assert not marker.exists()
    assert installs and "sync" in installs[0][0]
    assert all(argv[:2] == [node, str(cli)] for argv, _ in installs[1:])
    assert all(kw["env"]["PATH"].split(os.pathsep)[0] == str(Path(node).parent) for _, kw in installs)


@pytest.mark.windows_only
@pytest.mark.parametrize("custom_prefix", [False, True])
def test_windows_installer_finds_user_global_npm_upgrade(runtime, monkeypatch, tmp_path, custom_prefix):
    module, _, _, marker, node, make = runtime
    old_cli = make("11.11.0", "prefix", {"node": "*", "npm": ">=11.17.0"})
    prefix = old_cli.parents[3]
    shutil.copy2(node, prefix / "node.exe")  # Native Windows executable; never a simulated host.
    roaming = tmp_path / "Roaming kullanıcı"
    global_prefix = tmp_path / "custom npm" if custom_prefix else roaming / "npm"
    new_package = global_prefix / "node_modules/npm"
    shutil.copytree(old_cli.parent.parent, new_package)
    (new_package / "package.json").write_text(json.dumps({"name": "npm", "version": "11.17.0"}))
    monkeypatch.setenv("APPDATA", str(roaming))
    if custom_prefix:
        monkeypatch.setenv("npm_config_prefix", str(global_prefix))
    else:
        for key in list(os.environ):
            if key.lower() == "npm_config_prefix":
                monkeypatch.delenv(key)
    monkeypatch.setattr(sys, "argv", ["setup_zeus.py", "--web", "--check"])
    assert module.main() == 0
    command = module.npm_command(str(prefix / "npm.cmd"), dict(os.environ))
    assert Path(command[1]) == new_package / "bin/npm-cli.js"
    assert not marker.exists()
