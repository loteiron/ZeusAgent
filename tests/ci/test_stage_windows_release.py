"""Real Git and ZIP checks for the public Windows payload publication boundary."""
from __future__ import annotations

import hashlib
import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import zipfile

import pytest


@pytest.fixture
def release(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "scripts"))
    module = importlib.import_module("stage_windows_release")
    root, cache = tmp_path / "source", tmp_path / "tools"
    root.mkdir()
    cache.mkdir()
    files = {name: b"reviewed source\n" for name in module.export_sources.__globals__["REQUIRED_FILES"]}
    files.update({
        "pyproject.toml": b'[project]\nversion="0.22.0"\n',
        "apps/desktop/package.json": b'{"version":"0.22.0"}',
        "scripts/windows-runtime.mjs": b"export const reviewed = true;\n",
        "zeus_cli/web_dist/index.html": b"<html>public app</html>",
        "ui-tui/dist/entry.js": b"console.log('public TUI');",
    })
    for name, blob in files.items():
        file = root / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(blob)
    pins = {name: {"file": f"{name}.zip", "sha256": hashlib.sha256(name.encode()).hexdigest(),
                   "url": f"https://example.com/{name}.zip", "executable": f"{name}.exe"}
            for name in ("uv", "git", "rg", "node")}
    for name, pin in pins.items():
        (cache / pin["file"]).write_bytes(name.encode())
    monkeypatch.setattr(module, "PINS", pins)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "config", "core.autocrlf", "false"], cwd=root, check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                    "commit", "-qm", "reviewed fixture"], cwd=root, check=True)
    return module, root, cache, tmp_path / "published"


def test_complete_payload_has_unique_paths_valid_manifests_and_identical_reviewed_helper(release):
    module, root, cache, output = release
    receipt = module.stage(root, cache, output)
    assert not receipt["dirty"]
    manifest = json.loads((output / "runtime-manifest.json").read_text())
    assert module.digest(output / manifest["source"]["file"]) == manifest["source"]["sha256"]
    with zipfile.ZipFile(output / "zeus-source.zip") as archive:
        assert archive.testzip() is None
        assert len(archive.namelist()) == len(set(archive.namelist()))
        assert archive.read("zeus-agent/scripts/windows-runtime.mjs") == (output / "windows-runtime.mjs").read_bytes()
        for filename in ("SOURCE-MANIFEST.json", "BUILD-MANIFEST.json"):
            for row in json.loads(archive.read("zeus-agent/" + filename))["files"]:
                assert hashlib.sha256(archive.read("zeus-agent/" + row["path"])).hexdigest() == row["sha256"]
    before = (output / "runtime-manifest.json").read_bytes()
    with pytest.raises(ValueError, match="existing"):
        module.stage(root, cache, output)
    assert (output / "runtime-manifest.json").read_bytes() == before


def test_corrupt_tool_fails_without_publication(release):
    module, root, cache, output = release
    (cache / "uv.zip").write_bytes(b"corruption")
    with pytest.raises(ValueError, match="checksum"):
        module.stage(root, cache, output)
    assert not output.exists()


def test_tool_changed_after_initial_verification_never_publishes(release, monkeypatch):
    module, root, cache, output = release
    original = module.export_sources
    def export_then_change(*args, **kwargs):
        report = original(*args, **kwargs)
        (cache / "uv.zip").write_bytes(b"changed after checksum")
        return report
    monkeypatch.setattr(module, "export_sources", export_then_change)
    with pytest.raises(ValueError, match="checksum"):
        module.stage(root, cache, output)
    assert not output.exists()


def test_live_helper_changes_cannot_replace_reviewed_bootstrap(release, monkeypatch):
    module, root, cache, output = release
    original = module.export_sources
    def export_then_change(*args, **kwargs):
        report = original(*args, **kwargs)
        (root / "scripts/windows-runtime.mjs").write_text("unreviewed replacement")
        return report
    monkeypatch.setattr(module, "export_sources", export_then_change)
    try:
        module.stage(root, cache, output)
    except ValueError:
        assert not output.exists()
    else:
        with zipfile.ZipFile(output / "zeus-source.zip") as archive:
            assert archive.read("zeus-agent/scripts/windows-runtime.mjs") == (output / "windows-runtime.mjs").read_bytes()


def test_build_root_symlink_cannot_publish_external_files(release, tmp_path):
    module, root, cache, output = release
    build = root / "zeus_cli/web_dist"
    outside = tmp_path / "external"
    outside.mkdir()
    (outside / "index.html").write_text("outside private bytes")
    shutil.rmtree(build)
    try:
        build.symlink_to(outside, target_is_directory=True)
    except OSError:
        if os.name != "nt":
            pytest.skip("symlink creation unavailable")
        subprocess.run(["cmd.exe", "/c", "mklink", "/J", str(build), str(outside)], check=True, capture_output=True)
    with pytest.raises(ValueError, match="[Bb]uilt|[Bb]uild|outside|escape|symlink"):
        module.stage(root, cache, output, allow_dirty=True)
    assert not output.exists()


def test_missing_build_output_does_not_leave_a_partial_release(release):
    module, root, cache, output = release
    (root / "ui-tui/dist/entry.js").unlink()
    with pytest.raises(ValueError, match="Build"):
        module.stage(root, cache, output, allow_dirty=True)
    assert not output.exists()


def test_reserved_manifest_cannot_create_a_duplicate_archive_entry(release):
    module, root, cache, output = release
    (root / "BUILD-MANIFEST.json").write_text("unreviewed manifest")
    module.stage(root, cache, output, allow_dirty=True)
    with zipfile.ZipFile(output / "zeus-source.zip") as archive:
        assert archive.namelist().count("zeus-agent/BUILD-MANIFEST.json") == 1
        assert isinstance(json.loads(archive.read("zeus-agent/BUILD-MANIFEST.json"))["files"], list)


def test_destination_created_by_another_publisher_is_preserved(release, monkeypatch):
    module, root, cache, output = release
    original = module.shutil.copyfile
    def copy_then_claim(*args, **kwargs):
        copied = original(*args, **kwargs)
        if not output.exists():
            output.mkdir()
            (output / "other-release.txt").write_text("another publisher owns this")
        return copied
    monkeypatch.setattr(module.shutil, "copyfile", copy_then_claim)
    with pytest.raises(OSError):
        module.stage(root, cache, output)
    assert [file.name for file in output.iterdir()] == ["other-release.txt"]
    assert (output / "other-release.txt").read_text() == "another publisher owns this"
    assert not list(output.parent.glob(".zeus-release-*"))


def test_changing_built_bytes_cannot_publish_an_unverified_bundle(release, monkeypatch):
    module, root, cache, output = release
    original = zipfile.ZipFile.writestr
    def write_then_change(archive, entry, data, *args, **kwargs):
        result = original(archive, entry, data, *args, **kwargs)
        if getattr(entry, "filename", entry) == "zeus-agent/ui-tui/dist/entry.js":
            (root / "ui-tui/dist/entry.js").write_text("concurrently changed build")
        return result
    monkeypatch.setattr(zipfile.ZipFile, "writestr", write_then_change)
    with pytest.raises(ValueError, match="Built asset changed"):
        module.stage(root, cache, output)
    assert not output.exists()
