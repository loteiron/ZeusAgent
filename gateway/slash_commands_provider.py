"""Private Telegram custom-provider setup. Credentials never enter an agent turn."""
from __future__ import annotations

import asyncio
import contextlib
import shlex

from gateway.config import Platform
from gateway.slash_access import _coerce_id_list, policy_from_extra
from zeus_constants import get_zeus_home, reset_zeus_home_override, set_zeus_home_override

_USAGE = (
    "Custom provider setup (Telegram private chat only):\n"
    "/provider status\n"
    "/provider set <API-base-URL> <model-ID> <API-key-or-none> [chat_completions|responses]\n\n"
    "Example: /provider set http://127.0.0.1:20128/v1 my-model YOUR_KEY\n"
    "Use none only when the endpoint needs no key. The key is stored privately; "
    "Zeus will try to delete your setup message."
)


class GatewayProviderCommandsMixin:
    async def _handle_provider_command(self, event):
        lock = getattr(self, "_provider_configuration_lock", None)
        if lock is None:
            lock = self._provider_configuration_lock = asyncio.Lock()
        async with lock:
            return await self._configure_provider_command(event)

    async def _configure_provider_command(self, event):
        source = event.source
        if (event.internal or source.platform != Platform.TELEGRAM or source.chat_type != "dm"
                or not source.user_id):
            return "Custom provider setup is available only to an authorized owner in a private Telegram chat."
        adapter = self._adapter_for_source(source)
        platform_cfg = getattr(adapter, "config", None)
        if platform_cfg is None and not getattr(self.config, "multiplex_profiles", False):
            platform_cfg = self.config.platforms.get(Platform.TELEGRAM)
        extra = getattr(platform_cfg, "extra", {}) or {}
        policy = policy_from_extra(extra, "dm")
        allowed = extra.get("allow_from")
        if "allow_from" not in extra and not getattr(self.config, "multiplex_profiles", False):
            from gateway.authz_mixin import _platform_gate_env
            allowed = _platform_gate_env("TELEGRAM_ALLOWED_USERS")
        owners = policy.admin_user_ids if policy.enabled else _coerce_id_list(allowed)
        if str(source.user_id) not in owners:
            return "Custom provider setup requires an explicit Telegram owner in allow_admin_from or allow_from."

        # Read the original spelling: generic slash parsing normalizes Unicode dashes,
        # which must never alter a credential. Do not send parse errors back verbatim.
        raw = event.text.split(maxsplit=1)
        try:
            args = shlex.split(raw[1] if len(raw) == 2 else "")
        except ValueError:
            return "Could not parse the setup command. Check quoting and use /provider for help."
        profile_home = self._resolve_profile_home_for_source(source) or get_zeus_home()
        override = set_zeus_home_override(profile_home)
        try:
            if not args:
                return _USAGE
            if args == ["status"]:
                from zeus_cli.config import read_user_config_raw
                from agent.redact import redact_sensitive_text
                cfg = read_user_config_raw(profile_home / "config.yaml")
                model = cfg.get("model")
                if not isinstance(model, dict) or model.get("provider") != "custom":
                    return "No custom provider is active. Use /provider for setup."
                # Credentials (including URL credentials from legacy settings) are never displayed.
                from urllib.parse import urlsplit, urlunsplit
                url = urlsplit(str(model.get("base_url") or ""))
                safe_url = urlunsplit((url.scheme, url.netloc.rsplit("@", 1)[-1], url.path, "", ""))
                return redact_sensitive_text(f"Custom provider\nURL: {safe_url}\nModel: {model.get('default', '')}\nMode: {model.get('api_mode') or 'auto'}\nAPI key: hidden", force=True)
            if len(args) not in {4, 5} or args[0] != "set":
                return _USAGE
            source = await asyncio.to_thread(self._normalize_source_for_session_key, source)
            session_key = self._session_key_for_source(source)
            if self._is_session_running(session_key):
                return "An agent is running in this chat. Use /stop or wait for it to finish before changing the provider."
            if getattr(self, "_startup_restore_in_progress", False):
                return "The gateway is starting. Retry provider setup in a moment."
            from zeus_cli.custom_provider_configuration import configure_custom_provider
            from zeus_cli.model_switch import ModelSwitchResult
            from gateway.slash_commands_model import _ModelSwitchContext
            ctx = _ModelSwitchContext(session_key=session_key, source=source,
                                      config_path=profile_home / "config.yaml", persist_global=False)
            ctx.read_config()
            try:
                route = await asyncio.to_thread(configure_custom_provider, *args[1:])
            except ValueError as exc:
                return str(exc)  # validation errors contain fixed text, never submitted values
            except Exception:
                return "Could not save the custom provider. Check the profile's file permissions and retry."
            result = ModelSwitchResult(success=True, new_model=route["default"], target_provider="custom",
                                       provider_label="Custom", base_url=route["base_url"], api_mode=route["api_mode"],
                                       api_key="no-key-required" if args[3] == "none" else args[3])
            await self._record_model_switch(result, ctx, source=source, one_turn=False, picker=False)
            removed = False
            adapter = self._adapter_for_source(source)
            if adapter is not None and event.message_id:
                with contextlib.suppress(Exception):
                    removed = await adapter.delete_message(str(source.chat_id), str(event.message_id)) is True
                    if removed:
                        event.message_id = None
            note = " Setup message deleted." if removed else " Delete your setup message from Telegram if it contains a key."
            return "Saved custom provider. It applies to the next message here and is the default for new sessions. API key hidden." + note
        finally:
            reset_zeus_home_override(override)
