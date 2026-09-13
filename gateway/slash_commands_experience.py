"""Read-only project experience for explicitly authorized private Telegram owners."""
import asyncio

from gateway.config import Platform
from gateway.slash_access import _coerce_id_list, policy_from_extra


class GatewayExperienceCommandsMixin:
    async def _handle_experience_command(self, event):
        source = event.source
        if (event.internal or source.platform != Platform.TELEGRAM or source.chat_type != "dm"
                or not source.user_id):
            return "Project experience is available to its owner in a private Telegram chat."
        adapter = self._adapter_for_source(source)
        config = getattr(adapter, "config", None)
        multiplexed = getattr(self.config, "multiplex_profiles", False)
        if config is None and not multiplexed:
            config = self.config.platforms.get(Platform.TELEGRAM)
        extra = getattr(config, "extra", {}) or {}
        policy = policy_from_extra(extra, "dm")
        allowed = extra.get("allow_from")
        if "allow_from" not in extra and not multiplexed:
            from gateway.authz_mixin import _platform_gate_env
            allowed = _platform_gate_env("TELEGRAM_ALLOWED_USERS")
        owners = policy.admin_user_ids if policy.enabled else _coerce_id_list(allowed)
        if str(source.user_id) not in owners:
            return "Project experience requires an explicit owner in allow_admin_from or allow_from."
        profile_home = self._resolve_profile_home_for_source(source)

        def inspect():
            from zeus_constants import get_zeus_home, set_zeus_home_override, reset_zeus_home_override
            from zeus_cli.config import load_config
            from zeus_cli.experience_command import dispatch_experience_command

            override = set_zeus_home_override(profile_home or get_zeus_home())
            try:
                terminal = load_config().get("terminal", {})
                if terminal.get("backend", "local") != "local":
                    return "Experience inspection requires a local gateway workspace."
                root = terminal.get("cwd")
                if not root:
                    return "Choose a project with terminal.cwd before inspecting its experience."
                return dispatch_experience_command(event.get_command_args() or "", root=root)
            finally:
                reset_zeus_home_override(override)

        return await asyncio.to_thread(inspect)
