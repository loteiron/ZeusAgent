"""Resolve slash intent before a busy conversation can treat it as steering text."""

from __future__ import annotations


def stale_session_control_reply(runner, event, session_key):
    """Button actions are invalid after /new, reset, or rerouting while admission waits."""
    expected = (event.metadata or {}).get("gateway_control_session_id")
    if expected and ((event.metadata or {}).get("gateway_session_key") != session_key
                     or runner.session_store.peek_session_id(session_key) != expected):
        return "These controls expired when the session changed. Open /status again."
    return None


def resolve_busy_command(runner, event):
    """Resolve configured aliases without executing hooks, plugins, or shell commands."""
    from zeus_cli.commands import resolve_command

    command = event.get_command()
    seen = set()
    while command:
        definition = resolve_command(command)
        if definition is not None:
            return definition, None
        if command in seen or len(seen) >= 10:
            return None, "Quick command alias cycle detected. Check quick_commands in config.yaml."
        seen.add(command)
        quick = runner._hm_quick_commands().get(command)
        if not isinstance(quick, dict) or quick.get("type") != "alias":
            return None, busy_custom_command_reply(runner, event.source, command, quick is not None)
        denied = runner._check_slash_access(event.source, command)
        if denied is not None:
            return None, denied
        if runner._hm_expand_alias_quick_command(event, quick) is None:
            return None, f"Quick command '/{command}' has no target defined."
        command = event.get_command()
    return None, "Quick command target is not a valid slash command."


def busy_custom_command_reply(runner, source, command: str, is_quick: bool) -> str:
    """Unknown names get immediate guidance; custom code never executes inside a live turn."""
    from agent.skill_bundles import resolve_bundle_command_key
    from agent.skill_commands import resolve_skill_command_key
    from zeus_cli.plugins import get_plugin_command_handler

    known = (is_quick or get_plugin_command_handler(command.replace("_", "-")) is not None
             or resolve_skill_command_key(command) is not None
             or resolve_bundle_command_key(command) is not None)
    if known:
        denied = runner._check_slash_access(source, command)
        if denied is not None:
            return denied
        return (f"Agent is running — `/{command}` starts separate work and cannot run mid-turn. "
                "Wait for the current response, or use `/stop` first.")
    return runner._hm_unknown_slash_reply(command, source) or f"Command `/{command}` is unavailable."
