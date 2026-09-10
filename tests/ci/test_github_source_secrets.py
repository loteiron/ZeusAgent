"""Synthetic scanner exceptions cannot authorize production credentials."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


_SPEC = importlib.util.spec_from_file_location(
    "github_source", Path(__file__).resolve().parents[2] / "scripts/github_source.py"
)
assert _SPEC and _SPEC.loader
source = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(source)


@pytest.mark.parametrize("case", ["reviewed-fixture", "production-file", "missing-reason", "changed-value", "changed-path"])
def test_exceptions_require_a_reviewed_fixture_and_the_exact_path_and_value(tmp_path, case):
    candidate = b"ghp_" + hashlib.sha256(b"synthetic fixture, never a credential").hexdigest()[:36].encode()
    name = "runtime.txt" if case == "production-file" else "tests/fixture.txt"
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(candidate + (b"extra" if case == "changed-value" else b""))
    entry = {"path": "tests/different.txt" if case == "changed-path" else name,
             "rule": "github-token", "sha256": hashlib.sha256(candidate).hexdigest(),
             "reason": "Reviewed synthetic test value; never sent to a service."}
    if case == "missing-reason":
        entry.pop("reason")
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github/secret-scan-allowlist.json").write_text(json.dumps([entry]))
    report = source.inspect_sources(tmp_path, [name], required=set())
    assert report["ok"] is (case == "reviewed-fixture")
    assert candidate.decode() not in json.dumps(report)
