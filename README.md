<p align="center">
  <img src="assets/zeus-mark.svg" width="88" height="88" alt="ZeusAgent" />
</p>

<h1 align="center">ZeusAgent</h1>
<p align="center">A personal AI workspace for conversations, tools, and ongoing tasks.</p>
<p align="center">Desktop · Terminal · Web · Messaging</p>

ZeusAgent brings a shared agent core to an Electron desktop app, an interactive
terminal UI, a command line, and a web dashboard. Resume conversations, work with
files and tools, and extend the agent through skills, plugins, and MCP servers.

Its storm blue and copper visual identity connects the desktop, web, terminal,
and setup experience, with coordinated light and dark appearances.

## What you can do

- **Continue your work.** Persistent sessions, memory, and reusable skills keep
  context and workflows available between conversations.
- **Use real tools.** Work with files, execute terminal commands, browse the web,
  and connect additional capabilities through MCP and plugins.
- **Choose your model.** Configure supported cloud providers or compatible local
  model endpoints; keep provider credentials in your local configuration.
- **Organize ongoing tasks.** Delegate to subagents, schedule jobs, and manage
  separate profiles for different configurations and workspaces.
- **Connect messaging services.** Use the gateway with configured adapters such
  as Telegram, Discord, and Slack.
- **Pick your interface.** Use the same agent core from the desktop, CLI, Ink
  terminal UI, or web dashboard.

## Get started

This is a **development source distribution**. Download or clone the complete
repository, then run the following commands from its root directory.

### Requirements

| Component | Supported versions |
|---|---|
| Python | `>=3.11,<3.14` — Python 3.12 is a suitable starting point |
| Node.js, for interface builds | `^22.22.0 \|\| ^24.11.0 \|\| >=26.0.0` |
| npm, for interface builds | `<11.10.0 \|\| >=11.17.0` |
| Model access | A configured provider account or compatible local endpoint |

The version declarations in [pyproject.toml](pyproject.toml) and
[package.json](package.json) are authoritative. Setup downloads dependencies;
model access and any provider charges are separate.

### Desktop

```sh
python scripts/setup_zeus.py --desktop
python scripts/launch_zeus.py setup
python scripts/launch_zeus.py --desktop
```

Use `python3` on Linux or macOS if that is your Python executable. Setup builds
the desktop, terminal UI, and web dashboard, and creates an isolated Python
environment outside the source directory. Normal desktop launches use the built app.

### Terminal and web

For an installation without Electron, use `python scripts/setup_zeus.py --web`,
then `python scripts/launch_zeus.py setup` to select your model provider.

| Interface or action | Command |
|---|---|
| Command line | `python scripts/launch_zeus.py --cli` |
| Interactive terminal UI | `python scripts/launch_zeus.py --tui` |
| Web dashboard | `python scripts/launch_zeus.py dashboard` |
| Configured messaging gateway | `python scripts/launch_zeus.py gateway run` |
| Diagnostics | `python scripts/launch_zeus.py doctor` |
| Available commands | `python scripts/launch_zeus.py --help` |

The Python CLI can also be installed with `python scripts/setup_zeus.py` without
building the interfaces. Configure messaging credentials and authorized users
before starting a gateway.

## Development

Use `python scripts/launch_zeus.py --desktop-dev` for desktop live reload.
Install the complete Python test dependencies with
`python scripts/setup_zeus.py --test-all`; run Python tests through
`bash scripts/run_tests.sh` with `ZEUS_PYTHON` pointing to the installed interpreter.
Windows requires Git Bash for that test runner.

See [CONTRIBUTING.md](CONTRIBUTING.md) for development conventions and
[SECURITY.md](SECURITY.md) for security reporting. Keep credentials, conversations,
session databases, dependencies, and generated builds outside version control.

## Project status and origin

ZeusAgent is an independent derivative of
[Hermes Agent](https://github.com/NousResearch/hermes-agent), developed by
**Nous Research and its contributors**, based on upstream commit
`2237be355906fbe6065ce1815711eee52b2d646e` (0.21.1). It is not an official Nous Research release.

The fork adds its own visual identity and namespace, isolated ZeusAgent state,
source setup and launch tools, and changes to goal decisions, task migration,
retry handling, and Windows behavior. Core agent capabilities build on Hermes.

This repository currently provides source builds, without signed installers or
a configured ZeusAgent release/update service. Existing Hermes data and external
plugins are not automatically migrated to the ZeusAgent namespace.

The original **MIT license** and copyright notice are preserved in
[LICENSE](LICENSE); fork provenance and attribution are recorded in
[NOTICE.md](NOTICE.md). Third-party dependencies retain their own licenses.
