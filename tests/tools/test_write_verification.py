"""Tests for write_file post-write content verification (verified flag)."""

import json
import os
from unittest.mock import patch as mock_patch

import pytest

from tools.file_tools import read_file_tool, write_file_tool


@pytest.fixture
def workdir(tmp_path, monkeypatch):
    monkeypatch.setenv("ZEUS_HOME", str(tmp_path / ".zeus"))
    return tmp_path


class TestWriteVerification:
    def test_successful_write_reports_verified(self, workdir):
        f = workdir / "out.txt"
        r = json.loads(write_file_tool(str(f), "hello verified world\n", task_id="t-wv"))
        assert r.get("bytes_written") == len("hello verified world\n")
        assert r.get("verified") is True

    def test_unicode_content_verified(self, workdir):
        f = workdir / "uni.txt"
        content = "línea → uno · ✓\n"
        r = json.loads(write_file_tool(str(f), content, task_id="t-wv"))
        assert r.get("verified") is True

    def test_crlf_preservation_still_verifies(self, workdir):
        # Existing CRLF file: write_file converts LF content to CRLF before
        # writing; verification hashes the shim-adjusted content, so it must
        # still report verified.
        f = workdir / "win.txt"
        f.write_bytes(b"old line\r\n")
        assert "error" not in json.loads(read_file_tool(str(f), task_id="t-wv"))
        r = json.loads(write_file_tool(str(f), "new line\nsecond\n", task_id="t-wv"))
        assert "error" not in r
        assert r.get("verified") is True
        assert b"\r\n" in f.read_bytes()

    @pytest.mark.skipif(os.name == "nt", reason="Exercises the POSIX shell checksum transport")
    def test_hash_mismatch_is_hard_error(self, workdir):
        f = workdir / "bad.txt"
        import tools.file_operations as fo
        real_sha = fo.hashlib.sha256

        class _WrongHash:
            def __init__(self, *a, **k):
                self._h = real_sha(b"different content entirely")
            def hexdigest(self):
                return self._h.hexdigest()

        with mock_patch.object(fo.hashlib, "sha256", _WrongHash):
            r = json.loads(write_file_tool(str(f), "actual content\n", task_id="t-wv"))
        assert "error" in r
        assert "checksum mismatch" in r["error"]
        assert not f.exists()

    @pytest.mark.skipif(os.name == "nt", reason="Exercises the POSIX shell checksum transport")
    def test_transport_verification_failure_preserves_existing_file(self, workdir):
        # An interrupted integrity check must not replace the last complete file.
        f = workdir / "ok.txt"
        f.write_text("last complete version\n")
        assert "error" not in json.loads(read_file_tool(str(f), task_id="t-wv2"))
        import tools.file_operations as fo

        real_exec = fo.ShellFileOperations._exec

        def flaky_exec(self, cmd, **kw):
            if "sha256sum" in cmd:
                raise RuntimeError("no hash binary")
            return real_exec(self, cmd, **kw)

        with mock_patch.object(fo.ShellFileOperations, "_exec", flaky_exec):
            r = json.loads(write_file_tool(str(f), "replacement content\n", task_id="t-wv2"))
        assert "error" in r
        assert f.read_text() == "last complete version\n"
