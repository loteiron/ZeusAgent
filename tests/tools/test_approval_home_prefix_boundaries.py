"""Absolute homes with one directory must retain credential-write detection."""
from __future__ import annotations

import pytest

from tools import approval_detection as detection


@pytest.mark.parametrize("home", ["/root", "/singlehome"])
def test_single_directory_home_writes_keep_approval_boundary(home, monkeypatch):
    original_expanduser = detection.os.path.expanduser
    monkeypatch.setattr(
        detection.os.path, "expanduser",
        lambda value: home if value == "~" else original_expanduser(value),
    )
    dangerous, _, _ = detection.detect_dangerous_command(f"cat public-key >> {home}/.ssh/authorized_keys")
    assert dangerous
    assert not detection.detect_dangerous_command(f"cat notes > /backup{home}/notes.txt")[0]


@pytest.mark.parametrize("home,command", [
    ("/", "cat /etc/hosts"),
    ("C:\\", r"type C:\Windows\notes.txt"),
    ("relative/home", "cat relative/home/notes.txt"),
    ("/root", "cat /backup/root/notes.txt"),
    ("/home/alice", "cat /backup/home/alice/notes.txt"),
    ("/root", "cat /rooted/notes.txt"),
    (r"C:\Users\alice", r"type D:\backup\C:\Users\alice\notes.txt"),
])
def test_home_folding_never_rewrites_roots_relative_paths_or_suffixes(home, command):
    assert detection._fold_home_prefixes(command, [home], "~") == command


@pytest.mark.parametrize("home,command", [
    (r"C:\Users\Alice", r"cat key >> c:\users\alice\.ssh\authorized_keys"),
    (r"C:\Users\Alice", "cat key >> C:/USERS/ALICE/.ssh/authorized_keys"),
    (r"\\SERVER\Profiles\Alice", r"cat key >> \\server\profiles\alice\.ssh\authorized_keys"),
])
def test_windows_home_case_variants_share_one_approval_boundary(home, command):
    folded = detection._fold_home_prefixes(command, [home], "~")
    assert folded == "cat key >> ~/.ssh/authorized_keys"
    assert detection.detect_dangerous_command(folded)[0]
