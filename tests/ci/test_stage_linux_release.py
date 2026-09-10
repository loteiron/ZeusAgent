"""Linux publication keeps reviewed bytes, modes and installer identity together."""
from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path
import subprocess
import tarfile

import pytest


@pytest.fixture
def release(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "scripts"))
    module = importlib.import_module("stage_linux_release")
    root, cache = tmp_path / "source", tmp_path / "tools"
    root.mkdir()
    cache.mkdir()
    files = {name: b"reviewed source\n" for name in module.export_sources.__globals__["REQUIRED_FILES"]}
    files.update({
        "pyproject.toml": b'[project]\nversion="0.22.0"\n',
        "apps/desktop/package.json": b'{"version":"0.22.0"}',
        "scripts/linux-runtime.mjs": b"export const reviewed = true;\n",
        "scripts/run_tests.sh": b"#!/bin/bash\nexit 0\n",
        "zeus_cli/web_dist/index.html": b"<html>public app</html>",
        "ui-tui/dist/entry.js": b"console.log('public TUI');",
    })
    for name, blob in files.items():
        file = root / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(blob)
    (root / "scripts/run_tests.sh").chmod(0o755)
    pins = {name: {"file": f"{name}.tar.gz", "format": "tar.gz", "sha256": hashlib.sha256(name.encode()).hexdigest(),
                   "url": f"https://example.com/{name}.tar.gz", "executable": f"{name}/bin/{name}"}
            for name in ("uv", "node")}
    for name, pin in pins.items():
        (cache / pin["file"]).write_bytes(name.encode())
    monkeypatch.setattr(module, "PINS", pins)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "config", "core.autocrlf", "false"], cwd=root, check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "update-index", "--chmod=+x", "scripts/run_tests.sh"], cwd=root, check=True)
    subprocess.run(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                    "commit", "-qm", "reviewed fixture"], cwd=root, check=True)
    return module, root, cache, tmp_path / "published"


def test_release_preserves_execution_mode_and_all_source_build_hashes(release):
    module, root, cache, output = release
    receipt = module.stage(root, cache, output)
    assert not receipt["dirty"]
    manifest = json.loads((output / "linux-runtime-manifest.json").read_text())
    assert module.digest(output / manifest["source"]["file"]) == manifest["source"]["sha256"]
    assert manifest["source"]["format"] == "tar.gz"
    with tarfile.open(output / "zeus-source-linux.tar.gz") as archive:
        assert archive.getmember("zeus-agent/scripts/run_tests.sh").mode == 0o755
        assert archive.getmember("zeus-agent/pyproject.toml").mode == 0o644
        assert len(archive.getnames()) == len(set(archive.getnames()))
        assert all(item.isfile() and item.uid == item.gid == 0 for item in archive.getmembers())
        assert archive.extractfile("zeus-agent/scripts/linux-runtime.mjs").read() == (output / "linux-runtime.mjs").read_bytes()
        for filename in ("SOURCE-MANIFEST.json", "BUILD-MANIFEST.json"):
            for row in json.load(archive.extractfile("zeus-agent/" + filename))["files"]:
                assert hashlib.sha256(archive.extractfile("zeus-agent/" + row["path"]).read()).hexdigest() == row["sha256"]
    before = (output / "linux-runtime-manifest.json").read_bytes()
    with pytest.raises(ValueError, match="existing"):
        module.stage(root, cache, output)
    assert (output / "linux-runtime-manifest.json").read_bytes() == before


def test_same_reviewed_tree_and_builds_produce_identical_linux_source(release):
    module, root, cache, output = release
    module.stage(root, cache, output)
    other = output.with_name("second")
    module.stage(root, cache, other)
    assert module.digest(output / "zeus-source-linux.tar.gz") == module.digest(other / "zeus-source-linux.tar.gz")


@pytest.mark.parametrize("target", ["tool", "helper", "build", "commit"])
def test_concurrent_mutation_never_publishes_a_partial_linux_release(release, monkeypatch, target):
    module, root, cache, output = release
    original = module.export_sources
    def export_then_change(*args, **kwargs):
        result = original(*args, **kwargs)
        if target == "tool":
            (cache / "uv.tar.gz").write_bytes(b"corrupt")
        elif target == "helper":
            (root / "scripts/linux-runtime.mjs").write_text("unreviewed replacement")
        elif target == "build":
            (root / "ui-tui/dist/entry.js").unlink()
        else:
            subprocess.run(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                            "commit", "--allow-empty", "-qm", "concurrent commit"], cwd=root, check=True)
        return result
    monkeypatch.setattr(module, "export_sources", export_then_change)
    with pytest.raises(ValueError):
        module.stage(root, cache, output)
    assert not output.exists()


def test_reserved_metadata_is_generated_once(release):
    module, root, cache, output = release
    (root / "BUILD-MANIFEST.json").write_text("unreviewed manifest")
    module.stage(root, cache, output, allow_dirty=True)
    with tarfile.open(output / "zeus-source-linux.tar.gz") as archive:
        assert archive.getnames().count("zeus-agent/BUILD-MANIFEST.json") == 1
        assert json.load(archive.extractfile("zeus-agent/BUILD-MANIFEST.json"))["dirty"] is True
