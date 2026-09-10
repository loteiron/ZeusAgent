"""Validate source and package acceptance without granting publication authority."""
from pathlib import Path
import re

import yaml


ROOT = Path(__file__).resolve().parents[2]


def test_active_ci_is_read_only_pinned_and_has_no_publishing_authority():
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
        for job in workflow["jobs"].values():
            assert job.get("permissions", workflow["permissions"]) == expected_permissions
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
