"""Stage the reviewed Linux source, built interfaces and pinned bootstrap tools.

The tar payload preserves executable Git modes, excludes private source and state,
and carries the same source/build receipts as the Windows release.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import tomllib
import zipfile

from github_source import export_sources, source_paths
from stage_windows_release import add_built_assets, digest, verify_tool

ROOT = Path(__file__).resolve().parents[1]
PINS = {
    "uv": {
        "file": "uv-x86_64-unknown-linux-gnu.tar.gz", "format": "tar.gz",
        "url": "https://github.com/astral-sh/uv/releases/download/0.11.33/uv-x86_64-unknown-linux-gnu.tar.gz",
        "sha256": "aa9fca823c03289fb6e3460b3dc864f3ea895cafaf9b99247701a67b17d1b018",
        "executable": "uv-x86_64-unknown-linux-gnu/uv",
    },
    "node": {
        "file": "node-v22.23.2-linux-x64.tar.xz", "format": "tar.xz",
        "url": "https://nodejs.org/dist/v22.23.2/node-v22.23.2-linux-x64.tar.xz",
        "sha256": "d60acfe00a2932254bb0ad20e01b0d74397a0875595de719654b214f4b03f307",
        "executable": "node-v22.23.2-linux-x64/bin/node",
    },
}


def _add(runtime: tarfile.TarFile, name: str, blob: bytes, mode: int, seen: set[str]) -> None:
    if (not name.startswith("zeus-agent/") or "\\" in name
            or any(part in {"", ".", ".."} for part in name.split("/"))
            or name.casefold() in seen):
        raise ValueError(f"Unsafe or duplicate runtime archive path: {name}")
    seen.add(name.casefold())
    entry = tarfile.TarInfo(name)
    entry.mode = 0o755 if mode & 0o111 else 0o644
    entry.size = len(blob)
    # Fixed mtime, numeric owners and an empty gzip filename make the same
    # reviewed bytes reproducible regardless of build host or staging directory.
    runtime.addfile(entry, io.BytesIO(blob))


def stage(root: Path, cache: Path, output: Path, *, allow_dirty: bool = False) -> dict:
    root, output = root.resolve(), output.resolve()
    if output.exists():
        raise ValueError("Choose a new staging directory; existing release files are never overwritten.")
    if output == root or any(output.is_relative_to(root / folder) for folder in ("zeus_cli/web_dist", "ui-tui/dist")):
        raise ValueError("The release directory must be outside built asset directories.")
    status = subprocess.check_output(["git", "status", "--porcelain"], cwd=root)
    if status.strip() and not allow_dirty:
        raise ValueError("Commit the reviewed source before staging a release (or use --allow-dirty for local QA only).")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True, encoding="utf-8").strip()
    version = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    if json.loads((root / "apps/desktop/package.json").read_text(encoding="utf-8"))["version"] != version:
        raise ValueError("Desktop and backend versions must agree.")
    verified = {name: verify_tool(cache, pin) for name, pin in PINS.items()}
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="zeus-linux-source-") as temp, tempfile.TemporaryDirectory(prefix=".zeus-linux-release-", dir=output.parent) as staging:
        snapshot, built = Path(temp) / "source.zip", Path(temp) / "built.zip"
        paths = [name for name in source_paths(root, include_untracked=allow_dirty) if name != "BUILD-MANIFEST.json"]
        export_sources(root, paths, snapshot)
        with zipfile.ZipFile(built, "w") as archive:
            assets = add_built_assets(archive, root)
        payload = Path(staging) / "payload"
        payload.mkdir()
        destination = payload / "zeus-source-linux.tar.gz"
        seen: set[str] = set()
        with zipfile.ZipFile(snapshot) as source, zipfile.ZipFile(built) as frontend, destination.open("wb") as raw:
            reviewed_helper = source.read("ZeusAgent/scripts/linux-runtime.mjs")
            with gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0, compresslevel=6) as compressed:
                with tarfile.open(fileobj=compressed, mode="w|", format=tarfile.PAX_FORMAT) as runtime:
                    for archive in (source, frontend):
                        for entry in archive.infolist():
                            name = entry.filename.replace("ZeusAgent/", "zeus-agent/", 1)
                            _add(runtime, name, archive.read(entry), entry.external_attr >> 16, seen)
                    _add(runtime, "zeus-agent/BUILD-MANIFEST.json", (json.dumps({
                        "commit": commit, "dirty": bool(status.strip()), "files": assets,
                    }, indent=2) + "\n").encode(), 0o644, seen)
        for name, file in verified.items():
            copied = payload / PINS[name]["file"]
            shutil.copyfile(file, copied)
            if digest(copied) != PINS[name]["sha256"]:
                raise ValueError(f"Official tool checksum changed during staging: {file.name}")
        (payload / "linux-runtime.mjs").write_bytes(reviewed_helper)
        if digest(root / "scripts/linux-runtime.mjs") != hashlib.sha256(reviewed_helper).hexdigest():
            raise ValueError("Runtime helper changed after source inspection.")
        manifest = {
            "schemaVersion": 1, "version": version, "commit": commit, "python": "3.12.12",
            "source": {"file": destination.name, "root": "zeus-agent", "format": "tar.gz", "sha256": digest(destination),
                       "url": f"https://github.com/loteiron/ZeusAgent/releases/download/v{version}/{destination.name}"},
            "uv": PINS["uv"], "tools": {"node": PINS["node"]},
        }
        (payload / "linux-runtime-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        if subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True, encoding="utf-8").strip() != commit:
            raise ValueError("Source commit changed during release staging.")
        if not allow_dirty and subprocess.check_output(["git", "status", "--porcelain"], cwd=root).strip():
            raise ValueError("Source changed during release staging.")
        if os.name == "nt":
            payload.rename(output)
        else:
            output.mkdir()
            try:
                payload.replace(output)
            except BaseException:
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
