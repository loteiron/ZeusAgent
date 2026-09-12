"""Custom setup saves one route without exposing or borrowing credentials."""
import json
from pathlib import Path

import pytest
import yaml

from zeus_cli.custom_provider_configuration import configure_custom_provider


def test_saved_route_resolves_from_private_env_and_preserves_other_settings(monkeypatch, tmp_path):
    monkeypatch.setenv("ZEUS_HOME", str(tmp_path))
    (tmp_path / "config.yaml").write_text("telegram:\n  allow_from: ['owner']\nmodel:\n  context_length: 4096\n", encoding="utf-8")
    secret = "test-private-value"
    result = configure_custom_provider("http://127.0.0.1:20128/v1", "custom-model", secret)
    raw = (tmp_path / "config.yaml").read_text(encoding="utf-8")
    config = yaml.safe_load(raw)
    assert secret not in raw and secret not in json.dumps(result)
    assert config["telegram"]["allow_from"] == ["owner"]
    assert "context_length" not in config["model"]
    assert config["model"]["provider"] == "custom"
    from zeus_cli.config import get_env_value
    assert get_env_value(result["key_env"]) == secret
    from zeus_cli.runtime_provider import resolve_runtime_provider
    runtime = resolve_runtime_provider(requested="custom", target_model="custom-model")
    assert runtime["api_key"] == secret
    assert runtime["base_url"] == result["base_url"]


@pytest.mark.parametrize("url", ["file:///tmp/key", "https://user:pass@example.com/v1", "https://example.com/v1?key=secret", "https://example.com/#token", "http://example.com:invalid/v1", "https://example.com/\nfoo"])
def test_invalid_endpoint_never_writes_credentials(tmp_path, monkeypatch, url):
    monkeypatch.setenv("ZEUS_HOME", str(tmp_path))
    with pytest.raises(ValueError):
        configure_custom_provider(url, "model", "test-private-value")
    assert not (tmp_path / ".env").exists()
    assert not (tmp_path / "config.yaml").exists()


def test_no_key_is_explicit_and_does_not_borrow_another_endpoint_key(tmp_path, monkeypatch):
    monkeypatch.setenv("ZEUS_HOME", str(tmp_path))
    monkeypatch.setenv("OPENAI_API_KEY", "unrelated-private-value")
    configure_custom_provider("http://127.0.0.1:8999/v1", "local-model", "none")
    from zeus_cli.runtime_provider import resolve_runtime_provider
    runtime = resolve_runtime_provider(requested="custom", target_model="local-model")
    assert runtime["api_key"] == "no-key-required"


def test_failed_config_save_does_not_replace_the_old_routes_key(tmp_path, monkeypatch):
    monkeypatch.setenv("ZEUS_HOME", str(tmp_path))
    first = configure_custom_provider("http://127.0.0.1:8999/v1", "first", "old-private-value")
    before = (tmp_path / "config.yaml").read_bytes()
    def fail(*args, **kwargs):
        raise OSError("simulated disk failure")
    monkeypatch.setattr("zeus_cli.config.save_config", fail)
    with pytest.raises(OSError):
        configure_custom_provider("http://127.0.0.1:8999/v1", "next", "new-private-value")
    assert (tmp_path / "config.yaml").read_bytes() == before
    from zeus_cli.config import get_env_value
    assert get_env_value(first["key_env"]) == "old-private-value"
