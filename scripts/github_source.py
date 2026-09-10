"""Check/export a Git source tree without publishing private handoff evidence.

This is a conservative pre-publication check, not a complete secret scanner.
Only paths/rule names are printed when a candidate credential is found.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import tempfile
import zipfile


EXCLUDED_PARTS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".pytest_cache", ".ruff_cache"}
EXCLUDED_PREFIXES = (
    "verification/", "MagicMock/", "apps/desktop/dist/", "apps/desktop/build/",
    "apps/desktop/release/", "ui-tui/dist/", "zeus_cli/web_dist/",
)
PRIVATE_NAMES = {".env", ".op.env", "config.yaml", "cli-config.yaml", "auth.json", "cookies.txt"}
REQUIRED_FILES = {
    "LICENSE", "NOTICE.md", "README.md", "pyproject.toml", "uv.lock", "package.json", "package-lock.json",
    "zeus", "zeus_cli/main.py", "scripts/setup_zeus.py", "scripts/launch_zeus.py",
    ".github/workflows/zeus-ci.yml",
}
SECRET_RULES = {
    "github-token": re.compile(rb"(?:gh[pousr]_[A-Za-z0-9]{36,255}|github_pat_[A-Za-z0-9_]{40,255})"),
    "openai-style-token": re.compile(rb"sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{32,}"),
    "aws-access-key": re.compile(rb"(?:AKIA|ASIA)[A-Z0-9]{16}"),
    "private-key": re.compile(rb"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----[\r\n]+[A-Za-z0-9+/=\r\n]{64,}"),
}


def _sha(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def exportable(name: str) -> bool:
    parts = PurePosixPath(name).parts
    return (
        bool(parts) and not name.startswith(EXCLUDED_PREFIXES)
        and not (set(parts) & EXCLUDED_PARTS)
        and not any(part.endswith(".egg-info") for part in parts)
        and name not in {"SOURCE-MANIFEST.json", "ARSIV-MANIFEST.json", "SOHBET-NOTLARI.md", "ASTRA-DEVAM-NOTU.md", "ZEUS-DEVIR-NOTU.md"}
        and not name.endswith((".bundle", ".heapsnapshot"))
    )


def source_paths(root: Path, *, include_untracked: bool = False) -> list[str]:
    command = ["git", "ls-files", "--cached", "-z"]
    if include_untracked:
        command += ["--others", "--exclude-standard"]
    paths = subprocess.check_output(command, cwd=root).decode("utf-8").split("\0")
    return sorted({name for name in paths if exportable(name)})


def inspect_sources(root: Path, paths: list[str], *, required: set[str] = REQUIRED_FILES,
                    fingerprints: dict[str, str] | None = None) -> dict:
    issues = []
    counts = defaultdict(int)
    folded = {}
    allowlist_path = root / ".github" / "secret-scan-allowlist.json"
    try:
        allowlist = json.loads(allowlist_path.read_text(encoding="utf-8")) if allowlist_path.exists() else []
        if not isinstance(allowlist, list):
            raise ValueError("Expected an array")
    except (ValueError, OSError):
        issues.append({"path": ".github/secret-scan-allowlist.json", "rule": "invalid-fixture-exceptions"})
        allowlist = []
    allowed = set()
    for index, item in enumerate(allowlist):
        if (not isinstance(item, dict)
                or not isinstance(item.get("path"), str)
                or not item["path"].startswith(("tests/", "tests-js/"))
                or ".." in PurePosixPath(item["path"]).parts
                or not isinstance(item.get("rule"), str) or item["rule"] not in SECRET_RULES
                or not isinstance(item.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"])
                or not isinstance(item.get("reason"), str) or not item["reason"].strip()):
            issues.append({"path": ".github/secret-scan-allowlist.json", "rule": "invalid-fixture-exception", "entry": index})
            continue
        allowed.add((item["path"], item["rule"], item["sha256"]))
    used = set()
    for name in sorted(required - set(paths)):
        issues.append({"path": name, "rule": "required-source-missing"})
    for name in paths:
        if not exportable(name):
            issues.append({"path": name, "rule": "excluded-source"})
            continue
        pure = PurePosixPath(name)
        if pure.is_absolute() or ".." in pure.parts or "\\" in name:
            issues.append({"path": name, "rule": "unsafe-path"})
            continue
        path = root / pure
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            issues.append({"path": name, "rule": "symlink-or-outside-root"})
            continue
        if not path.is_file():
            issues.append({"path": name, "rule": "missing-file"})
            continue
        for size in range(1, len(pure.parts) + 1):
            component = "/".join(pure.parts[:size])
            previous = folded.setdefault(component.casefold(), component)
            if previous != component:
                issues.append({"path": name, "rule": "case-collision", "other": previous})
                break
        if path.stat().st_size > 100 * 1024 * 1024:
            issues.append({"path": name, "rule": "github-file-size-limit"})
            continue
        if (path.name in PRIVATE_NAMES or path.name.startswith(".env.")
                or path.suffix.lower() in {".db", ".sqlite", ".sqlite3", ".har"}) and not path.name.endswith((".example", ".sample", ".template")):
            # Deliberate fixtures are reviewed by the content rules below.
            if not name.startswith(("tests/", "tests-js/")):
                issues.append({"path": name, "rule": "private-state-file"})
        blob = path.read_bytes()
        if fingerprints is not None:
            fingerprints[name] = _sha(blob)
        counts["files"] += 1
        counts["bytes"] += len(blob)
        for rule, pattern in SECRET_RULES.items():
            for match in pattern.finditer(blob):
                candidate = match.group()
                identity = (name, rule, _sha(candidate))
                if identity in allowed:
                    used.add(identity)
                    continue
                # Explicit low-entropy examples are not usable credentials.
                tail = candidate.rsplit(b"_", 1)[-1] if rule == "github-token" else candidate[8:]
                if rule != "private-key" and len(set(tail)) < 8:
                    continue
                issues.append({"path": name, "rule": rule, "line": blob[:match.start()].count(b"\n") + 1,
                               "sha256": identity[2]})
    stale = allowed - used
    for name, rule, _fingerprint in sorted(stale):
        issues.append({"path": name, "rule": "stale-secret-exception", "exception_rule": rule})
    return {"ok": not issues, "counts": dict(counts), "issues": issues,
            "limitations": "Checks selected source files, not Git history. Heuristics cannot prove the absence of all secrets."}


def _git_index_modes(root: Path) -> dict[str, int]:
    # Windows stat infers execution from the extension and loses POSIX modes.
    # A .git file also identifies linked worktrees; fixture trees may have no Git.
    directory = root.resolve()
    if not any((parent / ".git").exists() for parent in (directory, *directory.parents)):
        return {}
    entries = subprocess.check_output(["git", "ls-files", "--stage", "-z"], cwd=root)
    modes = {}
    for entry in entries.split(b"\0"):
        if not entry:
            continue
        metadata, name = entry.split(b"\t", 1)
        mode, _object, stage = metadata.split()
        if stage != b"0":
            raise ValueError(f"Unmerged Git index entry: {name.decode('utf-8')}")
        modes[name.decode("utf-8")] = int(mode, 8)
    return modes


def export_sources(root: Path, paths: list[str], output: Path, *, required: set[str] = REQUIRED_FILES) -> dict:
    paths = sorted(set(paths))
    fingerprints: dict[str, str] = {}
    report = inspect_sources(root, paths, required=required, fingerprints=fingerprints)
    if not report["ok"]:
        raise ValueError(json.dumps(report, ensure_ascii=False))
    output = output.resolve()
    if output.exists() or output.is_relative_to(root.resolve()):
        raise ValueError("Choose a new output path outside the source tree.")
    indexed_modes = _git_index_modes(root)
    output.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    # An unfinished export never replaces a valid archive.
    with tempfile.NamedTemporaryFile(prefix="zeus-source-", suffix=".zip", dir=output.parent, delete=False) as temp:
        temporary = Path(temp.name)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for name in paths:
                source = root / name
                blob = source.read_bytes()
                if _sha(blob) != fingerprints[name]:
                    raise ValueError(f"Source changed after inspection: {name}")
                mode = indexed_modes.get(name)
                if mode is None:
                    mode = stat.S_IMODE(source.stat().st_mode)
                rows.append({"path": name, "bytes": len(blob), "sha256": _sha(blob), "executable": bool(mode & 0o111)})
                entry = zipfile.ZipInfo("ZeusAgent/" + name)
                entry.create_system = 3
                entry.external_attr = (stat.S_IFREG | (0o755 if mode & 0o111 else 0o644)) << 16
                entry.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(entry, blob)
            manifest = zipfile.ZipInfo("ZeusAgent/SOURCE-MANIFEST.json")
            manifest.create_system = 3
            manifest.external_attr = (stat.S_IFREG | 0o644) << 16
            manifest.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(manifest, json.dumps({
                "description": "Public source snapshot; excludes private handoff/test evidence and generated runtime dependencies.",
                "files": rows,
            }, ensure_ascii=False, indent=2) + "\n")
        with zipfile.ZipFile(temporary) as archive:
            if archive.testzip() is not None:
                raise ValueError("Export CRC verification failed.")
            for row in rows:
                if _sha(archive.read("ZeusAgent/" + row["path"])) != row["sha256"]:
                    raise ValueError("Export digest verification failed.")
        # Link creation refuses an output created concurrently (replace would clobber it).
        output.hardlink_to(temporary)
    finally:
        temporary.unlink(missing_ok=True)
    return {"output": str(output), "files": len(rows), "bytes": output.stat().st_size,
            "sha256": _sha(output.read_bytes()), "verified": True}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["check", "export"])
    parser.add_argument("--include-untracked", action="store_true", help="Include non-ignored new files after review.")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    paths = source_paths(root, include_untracked=args.include_untracked)
    if args.action == "check":
        report = inspect_sources(root, paths)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["ok"] else 1
    if args.output is None:
        parser.error("export requires --output.")
    try:
        report = export_sources(root, paths, args.output)
    except ValueError as exc:
        print(str(exc))
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
