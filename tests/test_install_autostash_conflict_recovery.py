"""Source distribution installers must refuse without changing a checkout.

The inherited remote installer is disabled: both a conflicting and a clean
managed checkout must retain their local edits, HEAD and stash.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
INSTALL_SH = REPO_ROOT / "scripts" / "install.sh"
INSTALL_PS1 = REPO_ROOT / "scripts" / "install.ps1"
POWERSHELL = next(
    (candidate for candidate in ("pwsh", "powershell") if shutil.which(candidate)),
    None,
)


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
    )


def _make_conflicted_managed_checkout(tmp_path: Path) -> Path:
    """Create a managed checkout whose autostash conflicts with its origin."""
    seed = tmp_path / "seed"
    seed.mkdir()
    _git(seed, "init")
    (seed / "tracked.txt").write_text("base\n", encoding="utf-8")
    _git(seed, "add", "tracked.txt")
    _git(seed, "commit", "-m", "base")
    _git(seed, "branch", "-M", "main")

    remote = tmp_path / "origin.git"
    _git(tmp_path, "init", "--bare", str(remote))
    _git(seed, "remote", "add", "origin", str(remote))
    _git(seed, "push", "-u", "origin", "main")

    managed = tmp_path / "zeus-agent"
    _git(tmp_path, "clone", "--branch", "main", str(remote), str(managed))

    (managed / "tracked.txt").write_text("local edit\n", encoding="utf-8")

    upstream = tmp_path / "upstream"
    _git(tmp_path, "clone", "--branch", "main", str(remote), str(upstream))
    (upstream / "tracked.txt").write_text("upstream edit\n", encoding="utf-8")
    _git(upstream, "commit", "-am", "upstream")
    _git(upstream, "push", "origin", "main")

    return managed


def _checkout_snapshot(repo: Path) -> tuple[str, str, str]:
    return tuple(_git(repo, *args).stdout for args in (
        ("rev-parse", "HEAD"), ("status", "--porcelain"), ("stash", "list"),
    ))


def _assert_source_refusal(repo: Path, result: subprocess.CompletedProcess, before) -> None:
    assert result.returncode != 0
    assert "scripts/setup_zeus.py" in result.stdout + result.stderr
    assert _checkout_snapshot(repo) == before



@pytest.mark.live_system_guard_bypass
@pytest.mark.skipif(
    shutil.which("git") is None or shutil.which("bash") is None,
    reason="needs git and bash",
)
def test_source_install_sh_preserves_conflicting_checkout(
    tmp_path: Path,
) -> None:
    managed = _make_conflicted_managed_checkout(tmp_path)
    before = _checkout_snapshot(managed)
    before = _checkout_snapshot(managed)
    env = os.environ | {
        "ZEUS_HOME": str(tmp_path / "zeus-home"),
        "ZEUS_INSTALL_DIR": str(managed),
    }

    result = subprocess.run(
        ["bash", str(INSTALL_SH), "--stage", "repository", "--non-interactive"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )

    _assert_source_refusal(managed, result, before)
    assert (managed / "tracked.txt").read_text() == "local edit\n"


@pytest.mark.live_system_guard_bypass
@pytest.mark.skipif(
    shutil.which("git") is None or POWERSHELL is None,
    reason="needs git and PowerShell",
)
def test_source_install_ps1_preserves_conflicting_checkout(
    tmp_path: Path,
) -> None:
    managed = _make_conflicted_managed_checkout(tmp_path)
    before = _checkout_snapshot(managed)
    result = subprocess.run(
        [
            POWERSHELL,
            "-NoProfile",
            "-File",
            str(INSTALL_PS1),
            "-Stage",
            "repository",
            "-NonInteractive",
            "-InstallDir",
            str(managed),
            "-ZeusAgentHome",
            str(tmp_path / "zeus-home"),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )

    _assert_source_refusal(managed, result, before)
    assert (managed / "tracked.txt").read_text() == "local edit\n"


@pytest.mark.live_system_guard_bypass
@pytest.mark.skipif(
    shutil.which("git") is None or shutil.which("bash") is None,
    reason="needs git and bash",
)
def test_source_install_sh_preserves_clean_checkout(
    tmp_path: Path,
) -> None:
    """A clean local edit must survive refusal without fetching upstream."""
    seed = tmp_path / "seed"
    seed.mkdir()
    _git(seed, "init")
    (seed / "tracked.txt").write_text("base\n", encoding="utf-8")
    _git(seed, "add", "tracked.txt")
    _git(seed, "commit", "-m", "base")
    _git(seed, "branch", "-M", "main")

    remote = tmp_path / "origin.git"
    _git(tmp_path, "init", "--bare", str(remote))
    _git(seed, "remote", "add", "origin", str(remote))
    _git(seed, "push", "-u", "origin", "main")

    managed = tmp_path / "zeus-agent"
    _git(tmp_path, "clone", "--branch", "main", str(remote), str(managed))

    # Local edit on a file upstream will NOT touch — no conflict on apply.
    (managed / "local-only.txt").write_text("local edit\n", encoding="utf-8")

    upstream = tmp_path / "upstream"
    _git(tmp_path, "clone", "--branch", "main", str(remote), str(upstream))
    (upstream / "tracked.txt").write_text("upstream edit\n", encoding="utf-8")
    _git(upstream, "commit", "-am", "upstream")
    _git(upstream, "push", "origin", "main")

    before = _checkout_snapshot(managed)
    env = os.environ | {
        "ZEUS_HOME": str(tmp_path / "zeus-home"),
        "ZEUS_INSTALL_DIR": str(managed),
    }
    result = subprocess.run(
        ["bash", str(INSTALL_SH), "--stage", "repository", "--non-interactive"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )

    _assert_source_refusal(managed, result, before)
    assert (managed / "local-only.txt").read_text(encoding="utf-8") == "local edit\n"
    assert (managed / "tracked.txt").read_text(encoding="utf-8") == "base\n"
