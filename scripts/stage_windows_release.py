"""Stage the reviewed Windows runtime and pinned tools for NSIS/npm releases.

Build the web and TUI first. This stages public source, never a developer venv,
installed dependencies, authentication state, or a mutable upstream checkout.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import tomllib
import zipfile

from github_source import export_sources, source_paths

ROOT = Path(__file__).resolve().parents[1]
PINS = {
    "uv": {
        "file": "uv-windows-x64.zip",
        "cache": "uv-x86_64-pc-windows-msvc.zip",
        "url": "https://github.com/astral-sh/uv/releases/download/0.11.33/uv-x86_64-pc-windows-msvc.zip",
        "sha256": "c253ce868ad48d29327b661452ce184c9e333e6d6f5bc8d6fcfbf4dd52b83442",
        "executable": "uv.exe",
    },
    "git": {
        "file": "PortableGit-2.55.0.5-64-bit.7z.exe",
        "url": "https://github.com/git-for-windows/git/releases/download/v2.55.0.windows.5/PortableGit-2.55.0.5-64-bit.7z.exe",
        "sha256": "5aa8a20f6e9abb2c755f0e73c91c687701a46b309ad84a0ca6509380fa4ae290",
        "format": "7z-sfx",
        "executable": "bin/bash.exe",
    },
    "rg": {
        "file": "ripgrep-15.2.0-x86_64-pc-windows-msvc.zip",
        "url": "https://github.com/BurntSushi/ripgrep/releases/download/15.2.0/ripgrep-15.2.0-x86_64-pc-windows-msvc.zip",
        "sha256": "71b2fef860abe467217a538ff31de02f5258807c0129f771846f87bd029aafc5",
        "format": "zip",
        "executable": "ripgrep-15.2.0-x86_64-pc-windows-msvc/rg.exe",
    },
    "node": {
        "file": "node-v22.23.2-win-x64.zip",
        "url": "https://nodejs.org/dist/v22.23.2/node-v22.23.2-win-x64.zip",
        "sha256": "1177b4137ba5adaa56354ae40f1080c7450e8ae09cecb47da459d1c52ac99f97",
        "format": "zip",
        "executable": "node-v22.23.2-win-x64/node.exe",
    },
}


def digest(file: Path) -> str:
    with file.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify_tool(cache: Path, pin: dict) -> Path:
    file = cache / pin.get("cache", pin["file"])
    if not file.is_file() or file.is_symlink() or digest(file) != pin["sha256"]:
        raise ValueError(f"Missing or checksum-mismatched official tool asset: {file.name}")
    return file


def add_built_assets(archive: zipfile.ZipFile, root: Path) -> list[dict]:
    rows = []
    for directory, required in (("zeus_cli/web_dist", "index.html"), ("ui-tui/dist", "entry.js")):
        build = root / directory
        _check_built_path(build, root)
        if not (build / required).is_file():
            raise ValueError(f"Build {directory} before staging the release.")
        inventory = sorted(build.rglob("*"))
        for file in inventory:
            _check_built_path(file, root)
            if not file.is_file() or file.suffix == ".map":
                continue
            name = file.relative_to(root).as_posix()
            before = file.stat()
            blob = file.read_bytes()
            after = file.stat()
            _check_built_path(file, root)
            if (before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                    after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                raise ValueError(f"Built asset changed while reading: {name}")
            entry = zipfile.ZipInfo("zeus-agent/" + name)
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o100644 << 16
            archive.writestr(entry, blob)
            rows.append({"path": name, "bytes": len(blob), "sha256": hashlib.sha256(blob).hexdigest()})
        if sorted(build.rglob("*")) != inventory:
            raise ValueError(f"Build output changed during staging: {directory}")
    for row in rows:
        file = root / row["path"]
        _check_built_path(file, root)
        if digest(file) != row["sha256"]:
            raise ValueError(f"Built asset changed during staging: {row['path']}")
    return rows


def _check_built_path(file: Path, root: Path) -> None:
    """Reject an escaped build root as well as nested symlinks/junctions."""
    if not file.resolve().is_relative_to(root.resolve()):
        raise ValueError("Built asset escapes the source directory.")
    for component in (file, *file.parents):
        if component == root:
            break
        if component.is_symlink() or getattr(component, "is_junction", lambda: False)():
            raise ValueError("Built assets cannot contain symlinks or junctions.")


def stage(root: Path, cache: Path, output: Path, *, allow_dirty: bool = False) -> dict:
    root = root.resolve()
    output = output.resolve()
    if output.exists():
        raise ValueError("Choose a new staging directory; existing release files are never overwritten.")
    if output == root or any(output.is_relative_to(root / directory) for directory in ("zeus_cli/web_dist", "ui-tui/dist")):
        raise ValueError("The release directory must be outside built asset directories.")
    status = subprocess.check_output(["git", "status", "--porcelain"], cwd=root)
    if status.strip() and not allow_dirty:
        raise ValueError("Commit the reviewed source before staging a release (or use --allow-dirty for local QA only).")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True, encoding="utf-8").strip()
    version = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    if json.loads((root / "apps/desktop/package.json").read_text(encoding="utf-8"))["version"] != version:
        raise ValueError("Desktop and backend versions must agree.")
    verified = {name: verify_tool(cache, pin) for name, pin in PINS.items()}
    helper = root / "scripts/windows-runtime.mjs"
    if not helper.is_file():
        raise ValueError("Windows runtime helper is missing.")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="zeus-release-source-") as temp, tempfile.TemporaryDirectory(prefix=".zeus-release-", dir=output.parent) as staging:
        snapshot = Path(temp) / "source.zip"
        paths = [name for name in source_paths(root, include_untracked=allow_dirty) if name != "BUILD-MANIFEST.json"]
        export_sources(root, paths, snapshot)
        payload = Path(staging) / "payload"
        payload.mkdir()
        destination = payload / "zeus-source.zip"
        with zipfile.ZipFile(snapshot) as source, zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as runtime:
            for entry in source.infolist():
                blob = source.read(entry)
                renamed = copy.copy(entry)
                renamed.filename = renamed.orig_filename = "zeus-agent/" + entry.filename.removeprefix("ZeusAgent/")
                runtime.writestr(renamed, blob)
            reviewed_helper = source.read("ZeusAgent/scripts/windows-runtime.mjs")
            assets = add_built_assets(runtime, root)
            runtime.writestr("zeus-agent/BUILD-MANIFEST.json", json.dumps({"commit": commit, "dirty": bool(status.strip()), "files": assets}, indent=2) + "\n")
        with zipfile.ZipFile(destination) as runtime:
            if len(runtime.namelist()) != len({name.casefold() for name in runtime.namelist()}) or runtime.testzip() is not None:
                raise ValueError("Runtime archive failed CRC verification.")
        for name, file in verified.items():
            copied = payload / PINS[name]["file"]
            shutil.copyfile(file, copied)
            if digest(copied) != PINS[name]["sha256"]:
                raise ValueError(f"Official tool checksum changed during staging: {file.name}")
        (payload / "windows-runtime.mjs").write_bytes(reviewed_helper)
        if digest(helper) != hashlib.sha256(reviewed_helper).hexdigest():
            raise ValueError("Runtime helper changed after source inspection.")
        public_pins = {name: {key: value for key, value in pin.items() if key != "cache"} for name, pin in PINS.items()}
        manifest = {
            "schemaVersion": 1, "version": version, "commit": commit, "python": "3.12.12",
            "source": {"file": "zeus-source.zip", "root": "zeus-agent", "sha256": digest(destination),
                       "url": f"https://github.com/loteiron/ZeusAgent/releases/download/v{version}/zeus-source.zip"},
            "uv": public_pins.pop("uv"), "tools": public_pins,
        }
        (payload / "runtime-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        if subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True, encoding="utf-8").strip() != commit:
            raise ValueError("Source commit changed during release staging.")
        if not allow_dirty and subprocess.check_output(["git", "status", "--porcelain"], cwd=root).strip():
            raise ValueError("Source changed during release staging.")
        # Reserve the destination first: even an empty directory created by
        # another publisher must not be overwritten by POSIX directory rename.
        if os.name == "nt":
            # Windows rename already refuses an existing target directory.
            payload.rename(output)
        else:
            output.mkdir()
            try:
                payload.replace(output)
            except BaseException:
                # Remove only our still-empty reservation; never concurrent files.
                try:
                    output.rmdir()
                except OSError:
                    pass
                raise
        return {"output": str(output), "version": version, "commit": commit, "dirty": bool(status.strip()),
                "assets": [{"file": file.name, "sha256": digest(file), "bytes": file.stat().st_size} for file in sorted(output.iterdir())]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--allow-dirty", action="store_true", help="Local QA only; final release staging requires a clean commit.")
    args = parser.parse_args()
    print(json.dumps(stage(ROOT, args.cache, args.output, allow_dirty=args.allow_dirty), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
