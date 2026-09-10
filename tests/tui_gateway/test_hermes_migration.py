"""Real registry import, profile binding, and preview-only Hermes migration RPCs."""
import importlib
import json

import pytest


@pytest.fixture
def context(tmp_path, monkeypatch):
    source, first, second = (tmp_path / name for name in ("hermes", "first", "second"))
    for home in (source, first, second):
        home.mkdir()
    (source / "config.yaml").write_text("model: imported\napi_key: very-secret-value\n", encoding="utf-8")
    monkeypatch.setenv("ZEUS_HOME", str(first))
    server = importlib.import_module("tui_gateway.server")
    monkeypatch.setattr(server, "_profile_home", lambda name: {"first": first, "second": second}.get(name))
    return server, source, first, second


def test_rpc_preview_binds_to_profile_and_does_not_import(context):
    server, source, first, second = context
    response = server._methods["hermes.migration.scan"](1, {"source": str(source), "profile": "second"})
    preview = response["result"]["preview"]
    assert preview["target"] == str(second.resolve())
    assert "very-secret-value" not in json.dumps(response)
    assert not (second / "config.yaml").exists()
    params = {"source": str(source), "scan_id": preview["scan_id"], "categories": ["settings"]}
    assert "error" in server._methods["hermes.migration.import"](2, {**params, "profile": "first"})
    result = server._methods["hermes.migration.import"](3, {**params, "profile": "second"})
    assert result["result"]["result"]["imported"]["settings"] == 1
    assert not (first / "config.yaml").exists()
    assert (second / "config.yaml").read_text() == "model: imported\n"


def test_rpc_malformed_yaml_errors_do_not_reveal_contents(context):
    server, source, _, _ = context
    (source / "config.yaml").write_text("[very-secret-value", encoding="utf-8")
    result = server._methods["hermes.migration.scan"](1, {"source": str(source)})
    assert "error" in result
    assert "very-secret-value" not in json.dumps(result)


def test_rpc_omitted_preview_and_unsupported_categories_are_refused(context):
    server, source, first, _ = context
    result = server._methods["hermes.migration.import"](1, {"source": str(source), "categories": ["credentials"]})
    assert "error" in result
    assert not (first / "config.yaml").exists()
