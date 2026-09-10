"""Behavioral checks for the public-source export boundary."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import stat
import subprocess
import zipfile

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "github_source", Path(__file__).resolve().parents[2] / "scripts/github_source.py"
)
assert _SPEC and _SPEC.loader
source = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(source)


@pytest.mark.parametrize("case", ["changed-after-check", "private-handoff", "private-state", "secret"])
def test_unreviewed_or_private_bytes_never_reach_an_archive(tmp_path, monkeypatch, case):
    root = tmp_path / "checkout"
    root.mkdir()
    name = {"private-handoff": "verification/session.log", "private-state": "state/session.db"}.get(case, "README.md")
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    candidate = b"ghp_" + hashlib.sha256(b"synthetic scanner fixture").hexdigest()[:36].encode()
    path.write_bytes(candidate if case == "secret" else b"reviewed public source\n")
    if case == "changed-after-check":
        original = source.inspect_sources

        def inspect_then_mutate(*args, **kwargs):
            report = original(*args, **kwargs)
            path.write_bytes(candidate)
            return report

        monkeypatch.setattr(source, "inspect_sources", inspect_then_mutate)
    output = tmp_path / "public.zip"
    with pytest.raises(ValueError) as error:
        source.export_sources(root, [name], output, required=set())
    assert candidate.decode() not in str(error.value)
    assert not output.exists()
    assert not list(tmp_path.glob("zeus-source-*.zip"))


def test_export_is_reproducible_verified_and_never_overwrites(tmp_path):
    root = tmp_path / "checkout"
    root.mkdir()
    inputs = {"Türkçe not.md": b"hello\n", "bin/zeus": b"#!/bin/sh\nexit 0\n"}
    for name, blob in inputs.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(blob)
    (root / "bin/zeus").chmod(0o755)
    first, second = tmp_path / "one.zip", tmp_path / "two.zip"
    receipt = source.export_sources(root, list(inputs), first, required=set())
    source.export_sources(root, list(reversed(inputs)), second, required=set())
    assert receipt["verified"] and receipt["files"] == len(inputs)
    assert first.read_bytes() == second.read_bytes()
    with zipfile.ZipFile(first) as archive:
        assert archive.testzip() is None
        manifest = json.loads(archive.read("ZeusAgent/SOURCE-MANIFEST.json"))
        assert {row["path"] for row in manifest["files"]} == set(inputs)
        for row in manifest["files"]:
            assert archive.read("ZeusAgent/" + row["path"]) == inputs[row["path"]]
            assert row["sha256"] == hashlib.sha256(inputs[row["path"]]).hexdigest()
    original = first.read_bytes()
    with pytest.raises(ValueError):
        source.export_sources(root, list(inputs), first, required=set())
    assert first.read_bytes() == original


def test_export_uses_git_index_modes_and_untracked_filesystem_mode(tmp_path):
    root = tmp_path / "checkout"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    executable = root / "run.sh"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o644)
    regular = root / "data.exe"
    regular.write_text("public source fixture\n", encoding="utf-8")
    regular.chmod(0o755)
    untracked = root / "untracked.sh"
    untracked.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    untracked.chmod(0o755)
    subprocess.run(["git", "add", "run.sh", "data.exe"], cwd=root, check=True)
    subprocess.run(["git", "update-index", "--chmod=+x", "run.sh"], cwd=root, check=True)
    subprocess.run(["git", "update-index", "--chmod=-x", "data.exe"], cwd=root, check=True)
    expected = {
        executable.name: True,
        regular.name: False,
        untracked.name: bool(untracked.stat().st_mode & 0o111),
    }
    assert not executable.stat().st_mode & 0o111
    output = tmp_path / "public.zip"
    source.export_sources(root, list(expected), output, required=set())
    with zipfile.ZipFile(output) as archive:
        manifest = json.loads(archive.read("ZeusAgent/SOURCE-MANIFEST.json"))
        assert {row["path"]: row["executable"] for row in manifest["files"]} == expected
        for name, is_executable in expected.items():
            mode = archive.getinfo("ZeusAgent/" + name).external_attr >> 16
            assert stat.S_ISREG(mode)
            assert stat.S_IMODE(mode) == (0o755 if is_executable else 0o644)


def test_export_without_git_preserves_filesystem_executable_mode(tmp_path):
    root = tmp_path / "checkout"
    root.mkdir()
    script = root / "run.sh"
    script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    script.chmod(0o755)
    expected = bool(script.stat().st_mode & 0o111)
    output = tmp_path / "public.zip"
    source.export_sources(root, [script.name], output, required=set())
    with zipfile.ZipFile(output) as archive:
        manifest = json.loads(archive.read("ZeusAgent/SOURCE-MANIFEST.json"))
        assert manifest["files"][0]["executable"] == expected
        mode = archive.getinfo("ZeusAgent/" + script.name).external_attr >> 16
        assert stat.S_IMODE(mode) == (0o755 if expected else 0o644)
