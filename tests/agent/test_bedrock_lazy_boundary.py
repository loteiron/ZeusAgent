"""Unselected provider helpers must not install an AWS SDK at agent startup."""
import builtins
import importlib
import sys
from types import ModuleType
from unittest.mock import Mock


def test_custom_provider_helpers_do_not_install_bedrock(monkeypatch):
    from tools import lazy_deps

    installer = Mock()
    monkeypatch.setattr(lazy_deps, "ensure", installer)
    monkeypatch.delitem(sys.modules, "agent.bedrock_adapter", raising=False)
    adapter = importlib.import_module("agent.bedrock_adapter")
    kwargs = {"base_url": "http://localhost:11434/v1", "api_key": "test-only"}
    adapter.configure_bedrock_openai_client_kwargs(kwargs)
    assert kwargs == {"base_url": "http://localhost:11434/v1", "api_key": "test-only"}
    installer.assert_not_called()


def test_missing_sdk_is_installed_when_bedrock_is_actually_required(monkeypatch):
    from agent import bedrock_adapter
    from tools import lazy_deps

    sdk = ModuleType("boto3")
    sdk.__version__ = "1.42.89"
    installed = False
    real_import = builtins.__import__

    def import_with_missing_sdk(name, *args, **kwargs):
        if name == "boto3":
            if not installed:
                raise ModuleNotFoundError("No module named 'boto3'", name="boto3")
            return sdk
        return real_import(name, *args, **kwargs)

    def install(feature, *, prompt):
        nonlocal installed
        assert feature == "provider.bedrock"
        assert prompt is False
        installed = True

    monkeypatch.setattr(builtins, "__import__", import_with_missing_sdk)
    monkeypatch.setattr(lazy_deps, "ensure", install)
    assert bedrock_adapter._require_boto3() is sdk
    assert installed
