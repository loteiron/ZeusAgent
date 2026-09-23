from types import SimpleNamespace

from tools.delegate_tool_config import _resolve_child_runtime


def test_inherited_route_keeps_named_provider_identity():
    parent = SimpleNamespace(model="vision-model", provider="custom", requested_provider="custom:vision",
                             base_url="https://gateway.invalid/v1", api_mode="chat_completions")
    kwargs = dict(model=None, override_provider=None, override_base_url=None, override_api_key=None,
                  override_api_mode=None, override_acp_command=None, override_acp_args=None)
    runtime = _resolve_child_runtime(parent, {}, "fake-key", **kwargs)
    assert runtime["requested_provider"] == "custom:vision"
    kwargs.update(override_provider="openai", override_base_url="https://api.openai.com/v1")
    runtime = _resolve_child_runtime(parent, {}, "fake-key", **kwargs)
    assert runtime["requested_provider"] == "openai"
