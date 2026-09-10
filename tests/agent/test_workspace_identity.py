"""Content identity must describe the source being checked without modifying Git."""
import os
from pathlib import Path
import subprocess

from agent.workspace_identity import capture_workspace


def _git(root: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(root), *args], stderr=subprocess.DEVNULL)


def _repository(root: Path) -> Path:
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "core.autocrlf", "false")
    (root / ".gitignore").write_text("build/\n", encoding="utf-8")
    (root / "code.py").write_text("value = 1\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "-c", "user.name=Test", "-c", "user.email=test@invalid.local", "commit", "-qm", "base")
    return root


def test_identity_changes_for_dirty_contents_untracked_contents_and_index_modes(tmp_path):
    root = _repository(tmp_path / "Türkçe workspace")
    first = capture_workspace(root)
    assert first["status"] == "ready" and first["fingerprint"]
    assert capture_workspace(root / ".git")["status"] == "unavailable"
    (root / "code.py").write_text("value = 2\n", encoding="utf-8")
    dirty = capture_workspace(root)
    porcelain = _git(root, "status", "--porcelain")
    (root / "code.py").write_text("value = 3\n", encoding="utf-8")
    changed_again = capture_workspace(root)
    assert _git(root, "status", "--porcelain") == porcelain
    assert len({first["fingerprint"], dirty["fingerprint"], changed_again["fingerprint"]}) == 3
    nested = root / "new" / "nested"
    nested.mkdir(parents=True)
    (nested / "new.py").write_text("one\n", encoding="utf-8")
    added = capture_workspace(root)
    (nested / "new.py").write_text("two\n", encoding="utf-8")
    edited = capture_workspace(root)
    assert added["fingerprint"] != edited["fingerprint"]
    _git(root, "update-index", "--chmod=+x", "code.py")
    assert capture_workspace(root)["fingerprint"] != edited["fingerprint"]
    (root / "code.py").unlink()
    assert capture_workspace(root)["fingerprint"] != edited["fingerprint"]


def test_identity_is_read_only_ignores_builds_and_detects_content_even_with_restored_mtime(tmp_path):
    root = _repository(tmp_path / "project")
    code = root / "code.py"
    index = root / ".git" / "index"
    index_before = index.read_bytes()
    initial = capture_workspace(root)
    (root / "build").mkdir()
    (root / "build" / "bundle.js").write_text("generated", encoding="utf-8")
    assert capture_workspace(root)["fingerprint"] == initial["fingerprint"]
    metadata = code.stat()
    code.write_text("value = 7\n", encoding="utf-8")
    os.utime(code, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
    assert capture_workspace(root)["fingerprint"] != initial["fingerprint"]
    assert index.read_bytes() == index_before
    outside = tmp_path / "plain"
    outside.mkdir()
    assert capture_workspace(outside)["status"] == "unavailable"
    assert not capture_workspace(outside)["fingerprint"]


def test_workspace_selection_ignores_ambient_git_redirection(tmp_path, monkeypatch):
    root = _repository(tmp_path / "selected")
    other = _repository(tmp_path / "other")
    expected = capture_workspace(root)
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(other))
    actual = capture_workspace(root)
    assert actual["root"] == expected["root"]
    assert actual["fingerprint"] == expected["fingerprint"]


def test_linked_worktrees_have_distinct_source_identity(tmp_path):
    root = _repository(tmp_path / "selected")
    linked = tmp_path / "linked"
    _git(root, "worktree", "add", "--detach", str(linked), "HEAD")
    original = capture_workspace(root)
    copy = capture_workspace(linked)
    assert copy["status"] == "ready"
    assert copy["head"] == original["head"]
    assert copy["fingerprint"] != original["fingerprint"]
    (linked / "code.py").write_text("value = 9\n", encoding="utf-8")
    assert capture_workspace(linked)["fingerprint"] != copy["fingerprint"]
    assert capture_workspace(root)["fingerprint"] == original["fingerprint"]
