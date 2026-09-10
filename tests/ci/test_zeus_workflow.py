"""Keep candidate execution read-only and draft visibility isolated from source."""
import ast
import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]


def test_active_ci_permissions_are_pinned_and_draft_access_is_isolated():
    files = sorted((ROOT / ".github/workflows").glob("*.y*ml"))
    contracts = {
        "zeus-ci.yml": (
            {"push", "pull_request", "workflow_dispatch"}, {"contents": "read"},
        ),
        "zeus-linux-cli.yml": ({"workflow_dispatch"}, {"contents": "read"}),
        # The install jobs download the build job's artifact with the Actions API.
        "zeus-linux-package.yml": (
            {"workflow_dispatch"}, {"contents": "read", "actions": "read"},
        ),
    }
    assert {path.name for path in files} == set(contracts)
    for path in files:
        source = path.read_text(encoding="utf-8")
        workflow = yaml.safe_load(source)
        expected_triggers, expected_permissions = contracts[path.name]
        # PyYAML's YAML 1.1 resolver may parse the key `on` as True.
        triggers = workflow.get("on", workflow.get(True))
        assert set(triggers) == expected_triggers, path.name
        assert workflow["permissions"] == expected_permissions, path.name
        assert "secrets." not in source, path.name
        for job_id, job in workflow["jobs"].items():
            job_permissions = expected_permissions
            if path.name == "zeus-linux-cli.yml" and job_id == "candidate":
                job_permissions = {"contents": "write"}
            assert job.get("permissions", workflow["permissions"]) == job_permissions
            assert not job.get("continue-on-error", False)
            assert 0 < job["timeout-minutes"] <= 120
            for step in job["steps"]:
                assert not step.get("continue-on-error", False)
                assert not re.search(
                    r"\b(?:npm\s+publish|pnpm\s+publish|yarn\s+(?:npm\s+)?publish"
                    r"|gh\s+release\s+(?:create|upload|edit|delete)|git\s+push)\b",
                    step.get("run", ""),
                ), path.name
                if "uses" in step:
                    assert re.fullmatch(r"[\w-]+/[\w-]+@[0-9a-f]{40}", step["uses"])
                    if step["uses"].startswith("actions/checkout@"):
                        assert step["with"]["persist-credentials"] is False


def test_draft_token_never_reaches_checkout_or_candidate_execution():
    workflow = yaml.safe_load((ROOT / ".github/workflows/zeus-linux-cli.yml").read_text(encoding="utf-8"))
    candidate = workflow["jobs"]["candidate"]
    command = workflow["jobs"]["command"]
    assert candidate["permissions"] == {"contents": "write"}
    assert "env" not in candidate
    download, upload = candidate["steps"]
    assert "uses" not in download
    assert download["env"]["GH_TOKEN"] == "${{ github.token }}"
    # The sole privileged shell step reads release bytes and hashes them. It must
    # never check out source, unpack a payload, install dependencies, or run it.
    shell, verifier = download["run"].split("python3 - <<'PY'\n", 1)
    assert verifier.endswith("\nPY\n")
    assert "${{" not in download["run"]
    shell_commands = [line.strip() for line in shell.splitlines() if line.strip()]
    assert shell_commands[0].startswith('[[ "$RELEASE_VERSION" =~ ')
    assert shell_commands[1] == 'mkdir "$RUNNER_TEMP/zeus-command-assets"'
    assert shell_commands[2].startswith('gh release download "v$RELEASE_VERSION" ')
    assert all(line.startswith("--pattern ") for line in shell_commands[3:])
    verifier_tree = ast.parse(verifier.removesuffix("PY\n"))
    assert not any(isinstance(node, ast.ImportFrom) for node in ast.walk(verifier_tree))
    imported = {item.name for node in ast.walk(verifier_tree) if isinstance(node, ast.Import) for item in node.names}
    assert imported == {"hashlib", "os", "pathlib", "re"}
    # The privileged verifier only reads ordinary files and hashes their bytes.
    # Adding an interpreter, dynamic import, or payload invocation needs review.
    allowed_calls = {"Path", "iterdir", "read_text", "splitlines", "fullmatch", "groups",
                     "sorted", "is_file", "is_symlink", "sha256", "open", "iter", "read", "update", "hexdigest"}
    for node in ast.walk(verifier_tree):
        if isinstance(node, ast.Call):
            name = node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
            assert name in allowed_calls
            if name == "open":
                assert ast.literal_eval(node.args[0]) == "rb"
    assert upload["uses"].startswith("actions/upload-artifact@")
    assert "run" not in upload and "env" not in upload
    assert upload["with"]["if-no-files-found"] == "error"
    assert candidate["outputs"]["artifact-id"] == "${{ steps.bundle.outputs.artifact-id }}"

    assert command["needs"] == "candidate"
    assert command["permissions"] == {"contents": "read"}
    assert "env" not in command
    artifact = next(step for step in command["steps"] if step.get("uses", "").startswith("actions/download-artifact@"))
    assert artifact["with"]["artifact-ids"] == "${{ needs.candidate.outputs.artifact-id }}"
    assert artifact["with"]["merge-multiple"] is True
    assert all("GH_TOKEN" not in step.get("env", {}) for step in command["steps"])
    assert all("gh release" not in step.get("run", "") for step in command["steps"])


@pytest.mark.parametrize("mutation", [None, "corrupt", "missing_checksum", "missing_asset", "traversal", "duplicate", "unexpected_asset"])
def test_draft_verifier_rejects_incomplete_or_changed_bytes_without_execution(tmp_path, mutation):
    workflow = yaml.safe_load((ROOT / ".github/workflows/zeus-linux-cli.yml").read_text(encoding="utf-8"))
    script = workflow["jobs"]["candidate"]["steps"][0]["run"].split("python3 - <<'PY'\n", 1)[1].removesuffix("PY\n")
    assets = tmp_path / "zeus-command-assets"
    assets.mkdir()
    names = ["loteiron-zeus-agent-0.22.0.tgz", "linux-runtime-manifest.json", "zeus-source-linux.tar.gz", "install-linux.sh"]
    checksums = []
    for name in names:
        # If verification accidentally executes the installer this creates a
        # visible marker; these bytes must be treated only as opaque data.
        blob = b"#!/bin/sh\ntouch candidate-was-executed\n" if name.endswith(".sh") else name.encode()
        (assets / name).write_bytes(blob)
        checksums.append(f"{hashlib.sha256(blob).hexdigest()}  {name}")
    # A release checksum file also lists assets for other platforms. Their bytes
    # are intentionally not downloaded, and must never be opened here.
    checksums.append(f"{'0' * 64}  setup.exe")
    if mutation == "corrupt":
        (assets / names[0]).write_bytes(b"changed after assembly")
    elif mutation == "missing_checksum":
        checksums.pop(0)
    elif mutation == "missing_asset":
        (assets / names[0]).unlink()
    elif mutation == "traversal":
        checksums.append(f"{'0' * 64}  ../outside")
    elif mutation == "duplicate":
        checksums.append(checksums[0])
    elif mutation == "unexpected_asset":
        (assets / "unexpected.sh").write_text("exit 1")
    (assets / "SHA256SUMS.txt").write_text("\n".join(checksums) + "\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-I", "-c", script], cwd=tmp_path,
        env={**os.environ, "RUNNER_TEMP": str(tmp_path), "RELEASE_VERSION": "0.22.0"},
        capture_output=True, text=True, timeout=15,
    )
    assert (result.returncode == 0) is (mutation is None), result.stderr
    assert not (tmp_path / "candidate-was-executed").exists()


def test_ci_declares_real_os_checks_and_nonempty_python_and_js_suites():
    workflow = yaml.safe_load((ROOT / ".github/workflows/zeus-ci.yml").read_text(encoding="utf-8"))
    jobs = workflow["jobs"]
    assert jobs["python"]["runs-on"] == "ubuntu-latest"
    python_commands = "\n".join(step.get("run", "") for step in jobs["python"]["steps"])
    assert "bash scripts/run_tests.sh" in python_commands
    assert "--locked" in python_commands and "--file-retries 0" in python_commands
    preflight = next(
        step["run"] for step in jobs["python"]["steps"]
        if "tests/ci/test_stage_windows_release.py" in step.get("run", "")
    )
    assert "tests/ci/test_zeus_workflow.py" in preflight
    assert set(jobs["platform"]["strategy"]["matrix"]["os"]) == {"windows-latest", "macos-latest"}
    assert jobs["platform"]["runs-on"] == "${{ matrix.os }}"
    platform_commands = "\n".join(step.get("run", "") for step in jobs["platform"]["steps"])
    assert "bash scripts/run_tests.sh" in platform_commands
    for regression in (
        "tests/tools/test_code_rpc_request_validation.py",
        "tests/zeus_cli/test_update_marker_validation.py",
        "tests/zeus_cli/test_local_runtime_credentials.py",
        "tests/zeus_cli/test_local_runtime_key_identity.py",
        "tests/zeus_cli/test_local_supervisor_stop_races.py",
        "tests/zeus_cli/test_local_supervisor_cleanup.py",
        "tests/zeus_cli/test_local_adopted_restart.py",
    ):
        assert regression in platform_commands
    javascript_commands = "\n".join(step.get("run", "") for step in jobs["javascript"]["steps"])
    assert "npm ci" in javascript_commands
    assert "--ignore-scripts" not in javascript_commands
    for workspace in ("ui-tui", "web", "apps/desktop", "tests-js"):
        assert workspace in javascript_commands
