"""Source launches must use this checkout and its isolated interpreter."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.fixture
def launcher(tmp_path, monkeypatch):
    script = Path(__file__).resolve().parents[2] / "scripts" / "launch_zeus.py"
    spec = importlib.util.spec_from_file_location("source_launcher_under_test", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    root = tmp_path / "Zeus kaynak Türkçe"
    root.mkdir()
    monkeypatch.setattr(module, "__file__", str(root / "scripts" / "launch_zeus.py"))
    state = tmp_path / "Zeus veri Türkçe"
    monkeypatch.setenv("ZEUS_HOME", str(state))
    python = state / "venvs" / "zeus-agent" / (
        "Scripts/python.exe" if os.name == "nt" else "bin/python"
    )
    python.parent.mkdir(parents=True)
    python.touch()
    electron_binary = root / "electron-runtime"
    electron_binary.touch()
    monkeypatch.setattr(
        module.subprocess, "run",
        Mock(return_value=SimpleNamespace(returncode=0, stdout=str(electron_binary))),
    )
    return module, root, state, python


def test_cli_uses_checkout_entry_and_preserves_working_directory(launcher, tmp_path, monkeypatch):
    module, root, state, python = launcher
    project = tmp_path / "working project"
    project.mkdir()
    monkeypatch.chdir(project)
    monkeypatch.setattr(sys, "argv", ["launch_zeus.py", "-p", "zeus", "--help"])
    child = Mock(return_value=17)
    monkeypatch.setattr(module.subprocess, "call", child)

    assert module.main() == 17
    argv = child.call_args.args[0]
    options = child.call_args.kwargs
    assert argv == [str(python), str(root / "zeus"), "-p", "zeus", "--help"]
    assert "cwd" not in options
    assert options["env"]["ZEUS_HOME"] == str(state)
    assert options["env"]["ZEUS_PYTHON"] == str(python)


def test_built_desktop_forwards_literal_arguments_and_pins_backend(launcher, monkeypatch):
    module, root, state, python = launcher
    desktop = root / "apps" / "desktop"
    for relative in ["dist/electron-main.mjs", "dist/index.html"]:
        path = desktop / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("built fixture", encoding="utf-8")
    electron_cli = root / "node_modules" / "electron" / "cli.js"
    electron_cli.parent.mkdir(parents=True)
    electron_cli.touch()
    node = str(root / "Node runtime" / "node")
    monkeypatch.setattr(module.shutil, "which", lambda name, **kw: node if name == "node" else None)
    monkeypatch.setenv("ZEUS_DESKTOP_PYTHON", "wrong-python")
    monkeypatch.setenv("ZEUS_DESKTOP_ZEUS_ROOT", "wrong-checkout")
    monkeypatch.setenv("ZEUS_DESKTOP_DEV_SERVER", "http://stale-dev-server.invalid")
    monkeypatch.setenv("ELECTRON_RUN_AS_NODE", "1")
    arguments = ["--user-data-dir=" + str(root / "app data"), "literal&argument"]
    monkeypatch.setattr(sys, "argv", ["launch_zeus.py", "--desktop", *arguments])
    child = Mock(return_value=23)
    monkeypatch.setattr(module.subprocess, "call", child)

    assert module.main() == 23
    assert child.call_args.args[0] == [node, str(electron_cli), str(desktop), *arguments]
    options = child.call_args.kwargs
    assert options["cwd"] == root
    assert not options.get("shell", False)
    env = options["env"]
    assert env["ZEUS_DESKTOP_PYTHON"] == str(python)
    assert env["ZEUS_DESKTOP_ZEUS_ROOT"] == str(root)
    assert env["ZEUS_HOME"] == str(state)
    assert "ZEUS_DESKTOP_DEV_SERVER" not in env
    assert "ELECTRON_RUN_AS_NODE" not in env


@pytest.mark.parametrize("missing", ["python", "node", "electron", "build"])
def test_incomplete_desktop_install_has_actionable_error(launcher, monkeypatch, capsys, missing):
    module, root, _, python = launcher
    monkeypatch.setattr(sys, "argv", ["launch_zeus.py", "--desktop"])
    monkeypatch.setattr(module.shutil, "which", lambda name, **kw: None if missing == "node" else name)
    if missing == "python":
        python.unlink()
    if missing != "electron":
        electron = root / "node_modules" / "electron" / "cli.js"
        electron.parent.mkdir(parents=True)
        electron.touch()
    if missing != "build":
        dist = root / "apps" / "desktop" / "dist"
        dist.mkdir(parents=True)
        (dist / "index.html").touch()
        (dist / "electron-main.mjs").touch()
    child = Mock(side_effect=AssertionError("An incomplete install must not start a child"))
    monkeypatch.setattr(module.subprocess, "call", child)

    assert module.main() == 2
    assert "setup_zeus.py --desktop" in capsys.readouterr().err
    child.assert_not_called()


def test_child_start_error_is_reported_without_traceback(launcher, monkeypatch, capsys):
    module, _, _, _ = launcher
    monkeypatch.setattr(sys, "argv", ["launch_zeus.py", "--help"])
    monkeypatch.setattr(module.subprocess, "call", Mock(side_effect=PermissionError("cannot execute")))

    assert module.main() == 2
    error = capsys.readouterr().err
    assert "cannot execute" in error
    assert "Traceback" not in error


@pytest.mark.parametrize("extra_args,npm_available", [([], True), ([], False), (["--inspect"], True)])
def test_desktop_development_is_explicit_and_never_loses_arguments(
    launcher, monkeypatch, capsys, extra_args, npm_available,
):
    module, root, _, python = launcher
    electron = root / "node_modules" / "electron" / "cli.js"
    electron.parent.mkdir(parents=True)
    electron.touch()
    monkeypatch.setattr(sys, "argv", ["launch_zeus.py", "--desktop-dev", *extra_args])
    monkeypatch.setattr(
        module.shutil, "which", lambda name, **kw: None if name == "npm" and not npm_available else name,
    )
    child = Mock(return_value=0)
    monkeypatch.setattr(module.subprocess, "call", child)
    if extra_args or not npm_available:
        assert module.main() == 2
        child.assert_not_called()
        assert "--desktop" in capsys.readouterr().err
    else:
        assert module.main() == 0
        assert child.call_args.args[0] == ["npm", "run", "dev", "--workspace", "apps/desktop"]
        assert child.call_args.kwargs["env"]["ZEUS_DESKTOP_PYTHON"] == str(python)


def test_cli_real_child_keeps_unicode_paths_and_exit_status(launcher, tmp_path, monkeypatch):
    module, root, state, python = launcher
    # A real interpreter exercises argument transport without an installed model/provider.
    python.unlink()
    if os.name == "nt":
        import venv
        venv.create(python.parent.parent, with_pip=False)
    else:
        python.symlink_to(sys.executable)
    (root / "zeus").write_text(
        "import json, os, sys\n"
        "print(json.dumps({'argv': sys.argv[1:], 'cwd': os.getcwd(), "
        "'home': os.environ['ZEUS_HOME'], 'python': sys.executable}))\n"
        "sys.exit(7)\n",
        encoding="utf-8",
    )
    project = tmp_path / "my project"
    project.mkdir()
    monkeypatch.chdir(project)
    arguments = ["--query", "Türkçe boşluk & $ literal"]
    monkeypatch.setattr(sys, "argv", ["launch_zeus.py", *arguments])
    observed = []

    def capture_child(argv, **options):
        with subprocess.Popen(argv, **options, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as process:
            stdout, stderr = process.communicate(timeout=10)
            result = SimpleNamespace(stdout=stdout, stderr=stderr, returncode=process.returncode)
        observed.append(json.loads(result.stdout))
        return result.returncode

    monkeypatch.setattr(module.subprocess, "call", capture_child)
    assert module.main() == 7
    assert observed == [{"argv": arguments, "cwd": str(project), "home": str(state), "python": str(python)}]


@pytest.mark.parametrize("failure", ["install-script-failed", "binary-missing", "probe-timeout"])
def test_partial_electron_install_is_rejected_before_launch(launcher, monkeypatch, capsys, failure):
    module, root, _, _ = launcher
    electron = root / "node_modules" / "electron" / "cli.js"
    electron.parent.mkdir(parents=True)
    electron.touch()
    dist = root / "apps" / "desktop" / "dist"
    dist.mkdir(parents=True)
    for name in ("electron-main.mjs", "index.html"):
        (dist / name).touch()
    monkeypatch.setattr(sys, "argv", ["launch_zeus.py", "--desktop"])
    monkeypatch.setattr(module.shutil, "which", lambda name, **kw: name)
    probe = Mock(return_value=SimpleNamespace(
        returncode=1 if failure == "install-script-failed" else 0,
        stdout=str(root / "missing-electron"),
    ))
    if failure == "probe-timeout":
        probe.side_effect = subprocess.TimeoutExpired(["node"], 10)
    monkeypatch.setattr(module.subprocess, "run", probe)
    child = Mock(side_effect=AssertionError("Incomplete Electron must not start"))
    monkeypatch.setattr(module.subprocess, "call", child)

    assert module.main() == 2
    assert "setup_zeus.py --desktop" in capsys.readouterr().err
    child.assert_not_called()


@pytest.mark.parametrize("mode", ["--help", "--desktop", "--desktop-dev"])
def test_source_launch_uses_the_managed_toolchain_from_setup(launcher, monkeypatch, mode):
    module, root, state, _ = launcher
    managed_bin = state / "node" / ("" if os.name == "nt" else "bin")
    managed_bin.mkdir(parents=True)
    node = managed_bin / ("node.exe" if os.name == "nt" else "node")
    npm = managed_bin / ("npm.cmd" if os.name == "nt" else "npm")
    for executable in (node, npm):
        executable.touch()
        executable.chmod(0o755)
    electron = root / "node_modules/electron/cli.js"
    electron.parent.mkdir(parents=True)
    electron.touch()
    dist = root / "apps/desktop/dist"
    dist.mkdir(parents=True)
    for name in ("electron-main.mjs", "index.html"):
        (dist / name).touch()
    monkeypatch.setattr(sys, "argv", ["launch_zeus.py", mode])
    child = Mock(return_value=0)
    monkeypatch.setattr(module.subprocess, "call", child)
    assert module.main() == 0
    assert child.call_args.kwargs["env"]["PATH"].split(os.pathsep)[0] == str(managed_bin)
    if mode != "--help":
        assert Path(child.call_args.args[0][0]) == (npm if mode == "--desktop-dev" else node)
