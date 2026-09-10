"""Tests for user-defined quick commands that bypass the agent loop."""
import os
import subprocess
import sys
import shlex
import json
from unittest.mock import MagicMock, patch
from rich.text import Text
import pytest


# ── CLI tests ──────────────────────────────────────────────────────────────

class TestCLIQuickCommands:
    """Test quick command dispatch in ZeusAgentCLI.process_command."""

    @staticmethod
    def _printed_plain(call_arg):
        if isinstance(call_arg, Text):
            return call_arg.plain
        return str(call_arg)

    def _make_cli(self, quick_commands):
        from cli import ZeusAgentCLI
        cli = ZeusAgentCLI.__new__(ZeusAgentCLI)
        cli.config = {"quick_commands": quick_commands}
        cli.console = MagicMock()
        cli.agent = None
        cli.conversation_history = []
        # session_id is accessed by the fallback skill/fuzzy-match path in
        # process_command; without it, tests that exercise `/alias args`
        # can trip an AttributeError when cross-test state leaks a skill
        # command matching the alias target.
        cli.session_id = "test-session"
        return cli

    def test_exec_command_runs_and_prints_output(self):
        cli = self._make_cli({"dn": {"type": "exec", "command": "echo daily-note"}})
        result = cli.process_command("/dn")
        assert result is True
        cli.console.print.assert_called_once()
        printed = self._printed_plain(cli.console.print.call_args[0][0])
        assert printed == "daily-note"

    def test_exec_command_uses_chat_console_when_tui_is_live(self):
        cli = self._make_cli({"dn": {"type": "exec", "command": "echo daily-note"}})
        cli._app = object()
        live_console = MagicMock()

        with patch("cli.ChatConsole", return_value=live_console):
            result = cli.process_command("/dn")

        assert result is True
        live_console.print.assert_called_once()
        printed = self._printed_plain(live_console.print.call_args[0][0])
        assert printed == "daily-note"
        cli.console.print.assert_not_called()








    def test_quick_command_takes_priority_over_skill_commands(self):
        """Quick commands must be checked before skill slash commands."""
        cli = self._make_cli({"mygif": {"type": "exec", "command": "echo overridden"}})
        with patch("cli._skill_commands", {"/mygif": {"name": "gif-search"}}):
            cli.process_command("/mygif")
        cli.console.print.assert_called_once()
        printed = self._printed_plain(cli.console.print.call_args[0][0])
        assert printed == "overridden"




# ── Gateway tests ──────────────────────────────────────────────────────────

class TestGatewayQuickCommands:
    """Test quick command dispatch in GatewayRunner._handle_message."""

    def _make_event(self, command, args=""):
        from gateway.config import Platform
        from gateway.platforms.event import MessageEvent
        from gateway.session import SessionSource
        # Typed messages have empty metadata. A free-form MagicMock invents a
        # truthy session-control binding and stops before the command executes.
        return MessageEvent(text=f"/{command} {args}".strip(), source=SessionSource(
            platform=Platform.TELEGRAM, chat_id="123", chat_type="dm",
            user_id="test_user", user_name="Test User"))

    @pytest.mark.asyncio
    async def test_exec_command_returns_output(self):
        from gateway.run import GatewayRunner
        runner = GatewayRunner.__new__(GatewayRunner)
        runner.config = {"quick_commands": {"limits": {"type": "exec", "command": "echo ok"}}}
        runner._running_agents = {}
        runner._pending_messages = {}
        runner._is_user_authorized = MagicMock(return_value=True)

        event = self._make_event("limits")
        result = await runner._handle_message(event)
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_exec_command_does_not_leak_credentials(self):
        """Quick command exec must sanitize env — API keys must not appear in output."""
        from gateway.run import GatewayRunner

        runner = GatewayRunner.__new__(GatewayRunner)
        runner.config = {"quick_commands": {"leak": {"type": "exec", "command": "env"}}}
        runner._running_agents = {}
        runner._pending_messages = {}
        runner._is_user_authorized = MagicMock(return_value=True)

        event = self._make_event("leak")
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-or-secret-12345"}):
            result = await runner._handle_message(event)

        assert "PATH=" in result or "Path=" in result, "The command never ran"
        assert "sk-or-secret-12345" not in result, \
            "Quick command leaked OPENROUTER_API_KEY — exec runs without env sanitization"

    @pytest.mark.asyncio
    async def test_exec_command_output_is_redacted(self, monkeypatch):
        """Quick command output must redact sensitive patterns before returning."""
        from gateway.run import GatewayRunner

        # Ensure redaction is active regardless of host ZEUS_REDACT_SECRETS state
        # or test ordering
        monkeypatch.setattr("agent.redact._REDACT_ENABLED", True)

        runner = GatewayRunner.__new__(GatewayRunner)
        runner.config = {"quick_commands": {"token": {"type": "exec", "command": "echo QUICK_RAN sk-ant-api03-supersecretkey1234567890"}}}
        runner._running_agents = {}
        runner._pending_messages = {}
        runner._is_user_authorized = MagicMock(return_value=True)

        event = self._make_event("token")
        result = await runner._handle_message(event)

        assert "QUICK_RAN" in result, "The command never reached output redaction"
        assert "supersecretkey1234567890" not in result, \
            "Quick command output not redacted — raw API key returned to user"


    @pytest.mark.asyncio
    @pytest.mark.parametrize("interruption", ["timeout", "cancel"])
    async def test_interruption_terminates_its_process_tree(self, tmp_path, monkeypatch, interruption):
        from gateway.run import GatewayRunner
        from agent.deadline import kill_process_tree
        import asyncio
        import psutil
        script = tmp_path / "slow.py"
        pids_file = tmp_path / "pids.json"
        script.write_text(
            "import json,os,subprocess,sys,time\n"
            "from pathlib import Path\n"
            "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])\n"
            "Path(sys.argv[1]).write_text(json.dumps([os.getpid(),child.pid]))\n"
            "time.sleep(60)\n", encoding="utf-8")
        argv = [sys.executable, str(script), str(pids_file)]
        command = subprocess.list2cmdline(argv) if os.name == "nt" else shlex.join(argv)
        runner = GatewayRunner.__new__(GatewayRunner)
        runner.config = {"quick_commands": {"slow": {"type": "exec", "command": command}}}
        runner._running_agents = {}
        runner._pending_messages = {}
        runner._is_user_authorized = MagicMock(return_value=True)

        event = self._make_event("slow")
        original_wait = asyncio.wait_for

        async def shorten_command_timeout(awaitable, timeout):
            if timeout == 30:
                for _ in range(200):
                    if pids_file.exists():
                        break
                    await asyncio.sleep(.025)
                if interruption == "cancel":
                    asyncio.get_running_loop().call_soon(asyncio.current_task().cancel)
                    return await original_wait(awaitable, timeout=30)
                return await original_wait(awaitable, timeout=.05)
            return await original_wait(awaitable, timeout=timeout)

        monkeypatch.setattr(asyncio, "wait_for", shorten_command_timeout)
        try:
            if interruption == "cancel":
                with pytest.raises(asyncio.CancelledError):
                    await runner._handle_message(event)
            else:
                result = await runner._handle_message(event)
                assert result is not None and "timed out" in result.lower()
            pids = json.loads(pids_file.read_text())
            assert all(not psutil.pid_exists(pid) or psutil.Process(pid).status() == psutil.STATUS_ZOMBIE for pid in pids)
        finally:
            if pids_file.exists():
                for pid in json.loads(pids_file.read_text()):
                    if psutil.pid_exists(pid):
                        kill_process_tree(pid)

    @pytest.mark.asyncio
    async def test_gateway_config_object_supports_quick_commands(self):
        from gateway.config import GatewayConfig
        from gateway.run import GatewayRunner

        runner = GatewayRunner.__new__(GatewayRunner)
        runner.config = GatewayConfig(
            quick_commands={"limits": {"type": "exec", "command": "echo ok"}}
        )
        runner._running_agents = {}
        runner._pending_messages = {}
        runner._is_user_authorized = MagicMock(return_value=True)

        event = self._make_event("limits")
        result = await runner._handle_message(event)
        assert result == "ok"
