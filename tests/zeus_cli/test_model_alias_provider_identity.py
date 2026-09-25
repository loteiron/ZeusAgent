class TestProviderOwnedAliases:
    @staticmethod
    def _explicit_switch_to_provider_b(monkeypatch, aliases, explicit="provider-b", extra_cfg=""):
        """``/model shared-model --provider provider-b`` against a real config.yaml, with the
        given direct aliases loaded. Only model validation is stubbed (no network)."""
        import os
        from pathlib import Path

        import zeus_cli.model_switch as ms
        from zeus_cli.config import load_config

        monkeypatch.setenv("PROVIDER_B_KEY", "sk-provider-b")
        (Path(os.environ["ZEUS_HOME"]) / "config.yaml").write_text(
            "model:\n  provider: provider-a\n  default: old-model\n"
            "providers:\n"
            "  provider-a:\n    base_url: https://api-a.example.com/v1\n"
            "  provider-b:\n    base_url: https://api-b.example.com/v1\n    key_env: PROVIDER_B_KEY\n"
            + extra_cfg)
        monkeypatch.setattr(ms, "DIRECT_ALIASES", aliases)
        monkeypatch.setattr("zeus_cli.models_validate.validate_requested_model",
            lambda *a, **kw: {"accepted": True, "persist": True, "recognized": True, "message": None})
        cfg = load_config()
        return ms.switch_model(
            "shared-model", "provider-a", "old-model",
            current_base_url="https://api-a.example.com/v1", current_api_key="sk-provider-a",
            explicit_provider=explicit, user_providers=cfg["providers"],
            custom_providers=cfg.get("custom_providers"))

    def test_explicit_provider_never_adopts_alias_bound_to_another_provider(self, monkeypatch):
        """An alias on another provider's endpoint that targets the same model id must not
        outrank --provider: the turn and the credential stay on the provider the user named."""
        from zeus_cli.model_switch import DirectAlias

        result = self._explicit_switch_to_provider_b(monkeypatch, {
            "a-alias": DirectAlias("shared-model", "custom", "https://alias-host.example.com/v1",
                                   api_key="sk-alias-host"),
        })

        assert result.success, result.error_message
        assert result.target_provider == "provider-b"
        assert result.base_url == "https://api-b.example.com/v1"
        assert result.api_key == "sk-provider-b"
        assert result.resolved_via_alias == ""

    def test_explicit_provider_prefers_its_own_alias_for_a_shared_model(self, monkeypatch):
        """Several aliases expose one model id: the one owned by the named provider wins,
        whatever the mapping order (provider spelling is normalized)."""
        from zeus_cli.model_switch import DirectAlias

        result = self._explicit_switch_to_provider_b(monkeypatch, {
            "a-alias": DirectAlias("shared-model", "custom", "https://alias-host.example.com/v1",
                                   api_key="sk-alias-host"),
            "b-alias": DirectAlias("shared-model", "Provider-B", "https://api-b.example.com/v2"),
        })

        assert result.success, result.error_message
        assert result.resolved_via_alias == "b-alias"
        assert result.base_url == "https://api-b.example.com/v2"
        assert result.api_key != "sk-alias-host"

    def test_explicit_provider_keeps_alias_owned_by_legacy_custom_provider(self, monkeypatch):
        """A legacy ``custom_providers`` entry resolves to ``custom:<name>``; an alias that names
        it by its bare name is still that provider's alias and keeps its own endpoint and key."""
        from zeus_cli.model_switch import DirectAlias

        result = self._explicit_switch_to_provider_b(monkeypatch, {
            "a-alias": DirectAlias("shared-model", "provider-a", "https://alias-host.example.com/v1",
                                   api_key="sk-alias-host"),
            "corp-alias": DirectAlias("shared-model", "corp-llm", "https://corp.example.com/v2",
                                      api_key="sk-corp-alias"),
        }, explicit="corp-llm", extra_cfg=(
            "custom_providers:\n  - name: corp-llm\n"
            "    base_url: https://corp.example.com/v1\n    api_key: sk-corp\n"))

        assert result.success, result.error_message
        assert result.target_provider == "custom:corp-llm"
        assert result.resolved_via_alias == "corp-alias"
        assert result.base_url == "https://corp.example.com/v2"
        assert result.api_key == "sk-corp-alias"

    def test_implicit_switch_prefers_alias_of_current_legacy_custom_provider(self, monkeypatch):
        """Without --provider the current provider still owns a shared model id: on
        ``custom:corp-llm`` the alias naming ``corp-llm`` wins over another provider's alias."""
        import os
        from pathlib import Path

        import zeus_cli.model_switch as ms
        from zeus_cli.config import load_config
        from zeus_cli.model_switch import DirectAlias

        (Path(os.environ["ZEUS_HOME"]) / "config.yaml").write_text(
            "model:\n  provider: custom:corp-llm\n  default: old-model\n"
            "providers:\n  provider-a:\n    base_url: https://api-a.example.com/v1\n"
            "custom_providers:\n  - name: corp-llm\n"
            "    base_url: https://corp.example.com/v1\n    api_key: sk-corp\n")
        monkeypatch.setattr(ms, "DIRECT_ALIASES", {
            "a-alias": DirectAlias("shared-model", "provider-a", "https://alias-host.example.com/v1",
                                   api_key="sk-alias-host"),
            "corp-alias": DirectAlias("shared-model", "corp-llm", "https://corp.example.com/v2",
                                      api_key="sk-corp-alias"),
        })
        monkeypatch.setattr("zeus_cli.models_validate.validate_requested_model",
            lambda *a, **kw: {"accepted": True, "persist": True, "recognized": True, "message": None})
        cfg = load_config()

        result = ms.switch_model(
            "shared-model", "custom:corp-llm", "old-model",
            current_base_url="https://corp.example.com/v1", current_api_key="sk-corp",
            user_providers=cfg["providers"], custom_providers=cfg.get("custom_providers"))

        assert result.success, result.error_message
        assert result.resolved_via_alias == "corp-alias"
        assert result.base_url == "https://corp.example.com/v2"
        assert result.api_key == "sk-corp-alias"
