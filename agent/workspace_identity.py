"""Read-only content identity for local coding checks.

Includes tracked files, index modes, and nonignored additions. Dependencies,
ignored build outputs, remote services, and the running environment are outside
this source identity; it is not a filesystem snapshot or a security boundary.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor

from zeus_cli._subprocess_compat import bounded_probe_run, noninteractive_git_env


_MAX_FILES = 20_000
_MAX_FILE_BYTES = 64 * 1024 * 1024
_MAX_SOURCE_BYTES = 256 * 1024 * 1024
_PROBE_SECONDS = 30


class _Unavailable(Exception):
    pass


def _git(root: Path, *args: str, allow_unborn: bool = False, deadline: float | None = None) -> bytes:
    env = noninteractive_git_env()
    # Session cwd owns this probe. Inherited Git plumbing must not redirect the
    # selected workspace into another index, object store, or working tree.
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE", "GIT_NAMESPACE",
                "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_CEILING_DIRECTORIES"):
        env.pop(key, None)
    env["GIT_OPTIONAL_LOCKS"] = "0"
    timeout = min(10, deadline - time.monotonic()) if deadline else 10
    if timeout <= 0:
        raise _Unavailable("Source inspection exceeded its time limit")
    result = bounded_probe_run(["git", "-C", str(root), *args], env=env, timeout=timeout, binary=True)
    if result is None:
        raise _Unavailable("Git source inspection failed or exceeded its time limit")
    if result.returncode:
        if allow_unborn and result.returncode == 1:
            return b""
        raise _Unavailable("Git could not inspect this workspace")
    return result.stdout


def _inventory(root: Path, deadline: float) -> tuple[bytes, bytes, bytes, bytes]:
    return (
        _git(root, "rev-parse", "--verify", "--quiet", "HEAD", allow_unborn=True, deadline=deadline).strip(),
        _git(root, "ls-files", "--stage", "-z", deadline=deadline),
        _git(root, "ls-files", "--others", "--exclude-standard", "-z", deadline=deadline),
        _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all", deadline=deadline),
    )


def _stamp(path: Path) -> tuple[int, ...] | None:
    try:
        value = path.lstat()
    except FileNotFoundError:
        return None
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns,
            value.st_ctime_ns, value.st_mode)


def _entries(index: bytes, untracked: bytes) -> dict[str, str]:
    entries = {}
    for record in index.split(b"\0"):
        if not record:
            continue
        metadata, raw_name = record.split(b"\t", 1)
        mode, _object_id, stage = metadata.split()
        if stage != b"0":
            raise _Unavailable("Resolve merge conflicts before verifying this workspace")
        if mode == b"160000":
            raise _Unavailable("Submodule contents require separate verification")
        if mode not in {b"100644", b"100755", b"120000"}:
            raise _Unavailable("Unsupported Git file type")
        entries[os.fsdecode(raw_name)] = mode.decode("ascii")
    for name in untracked.split(b"\0"):
        if name:
            entries[os.fsdecode(name)] = "untracked"
    if len(entries) > _MAX_FILES:
        raise _Unavailable("Workspace exceeds the source verification file limit")
    return entries


def _file_digest(item: tuple[str, Path, tuple[int, ...] | None], deadline: float) -> tuple[str, bytes]:
    name, path, before = item
    if time.monotonic() > deadline:
        raise _Unavailable("Source inspection exceeded its time limit")
    if before is None:
        return name, b"deleted"
    mode = before[-1]
    if stat.S_ISLNK(mode):
        # A link can expose input outside the inventoried source. Do not claim
        # to have verified that external input from the link's name alone.
        raise _Unavailable("Symbolic links require separate source verification")
    if not stat.S_ISREG(mode):
        raise _Unavailable("Workspace contains an unsupported file type")
    digest = hashlib.sha256()
    read_bytes = 0
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            read_bytes += len(block)
            if read_bytes > _MAX_FILE_BYTES or time.monotonic() > deadline:
                raise _Unavailable("Source inspection exceeded its size or time limit")
            digest.update(block)
    if _stamp(path) != before:
        raise _Unavailable("Source changed while it was being inspected")
    execution = (mode & 0o111) if os.name != "nt" else 0
    return name, str(execution).encode() + b":" + digest.digest()


def _changed_paths(status: bytes) -> list[str]:
    records = iter(status.split(b"\0"))
    result = []
    for record in records:
        if not record:
            continue
        result.append(os.fsdecode(record[3:]))
        if b"R" in record[:2] or b"C" in record[:2]:
            previous = next(records, b"")
            if previous:
                result.append(os.fsdecode(previous))
    return sorted(set(result))[:200]


def capture_workspace(cwd: str | Path | None) -> dict:
    """Describe the actual source bytes, returning an empty identity if uncertain.

    Every capture reads source contents: mtime/size-only caches cannot detect
    editors that preserve timestamps. Git's index and working tree are never changed.
    """
    root = Path(cwd or ".").resolve()
    result = {"root": str(root), "fingerprint": "", "head": "", "status": "unavailable",
              "reason": "Git workspace unavailable", "changed_paths": []}
    deadline = time.monotonic() + _PROBE_SECONDS
    try:
        if not root.is_dir():
            raise _Unavailable("Workspace directory is unavailable")
        root = Path(os.fsdecode(_git(root, "rev-parse", "--show-toplevel", deadline=deadline).strip())).resolve()
        result["root"] = str(root)
        inventory = _inventory(root, deadline)
        head, index, untracked, status = inventory
        entries = _entries(index, untracked)
        result.update(head=head.decode("ascii"), changed_paths=_changed_paths(status))
        files = []
        total_size = 0
        for name in sorted(entries):
            if time.monotonic() > deadline:
                raise _Unavailable("Source inspection exceeded its time limit")
            relative = PurePosixPath(name)
            if relative.is_absolute() or ".." in relative.parts or ".git" in relative.parts:
                raise _Unavailable("Git returned an unsafe source path")
            path = root / relative
            if not path.resolve().is_relative_to(root):
                raise _Unavailable("Source path resolves outside this workspace")
            stamp = _stamp(path)
            if stamp:
                if stamp[2] > _MAX_FILE_BYTES:
                    raise _Unavailable("A source file exceeds the verification size limit")
                total_size += stamp[2]
            if total_size > _MAX_SOURCE_BYTES:
                raise _Unavailable("Workspace exceeds the source verification size limit")
            files.append((name, path, stamp))
        digest = hashlib.sha256(b"zeus-source-v1\0" + os.fsencode(str(root)) + b"\0" + head + b"\0" + index)
        with ThreadPoolExecutor(max_workers=32, thread_name_prefix="zeus-source") as pool:
            for name, content in pool.map(lambda item: _file_digest(item, deadline), files):
                digest.update(os.fsencode(name) + b"\0" + entries[name].encode() + b"\0" + content + b"\0")
        if any(_stamp(path) != stamp for _name, path, stamp in files) or _inventory(root, deadline) != inventory:
            raise _Unavailable("Source changed while it was being inspected")
        result.update(status="ready", fingerprint=digest.hexdigest(), reason="", file_count=len(files))
    except _Unavailable as exc:
        result["reason"] = str(exc)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        result["reason"] = f"Source identity unavailable ({type(exc).__name__})"
    return result
