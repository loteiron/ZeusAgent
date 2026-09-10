"""The issue form must not require users to publish diagnostic bundles."""
from pathlib import Path
import re

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("name", ["bug_report.yml", "setup_help.yml", "feature_request.yml"])
def test_issue_diagnostics_are_optional_local_and_not_routed_to_upstream(name):
    form = yaml.safe_load((ROOT / ".github/ISSUE_TEMPLATE" / name).read_text())
    field = next(item for item in form["body"] if item.get("id") == "debug-report")
    assert not field.get("validations", {}).get("required", False)
    instructions = "\n".join(str(item.get("attributes", {})) for item in form["body"])
    assert not re.search(r"zeus debug share(?! --local)", instructions)
    assert "paste.rs" not in instructions
    assert "github.com/NousResearch" not in instructions
    assert "redact" in instructions.lower()
