<p align="center">
  <img src="assets/zeus-mark.svg" width="88" height="88" alt="ZeusAgent" />
</p>

<h1 align="center">ZeusAgent</h1>
<p align="center">A coding workspace that keeps evidence with the work.</p>
<p align="center">Desktop · Terminal · Web · Messaging</p>

ZeusAgent brings a shared agent core to an Electron desktop app, an interactive
terminal UI, a command line, and a web dashboard. Resume conversations, work with
files and tools, and extend the agent through skills, plugins, and MCP servers.

Its storm blue and copper visual identity connects the desktop, web, terminal,
and setup experience, with coordinated light and dark appearances.

## What you can do

- **See what was actually checked.** Inspect separate test, lint, build, and
  targeted-check results in Desktop's **Evidence** view. Source edits invalidate
  old results; an unrelated passing check cannot hide a failure.
- **Compare against a baseline.** Preserve observed results before editing and
  distinguish fixed failures, new regressions, and problems that already existed.
- **Require proof before delivery.** Goal quality gates record their workspace,
  timing, output, and source identity. Required checks must be current and passing
  before the goal can be marked complete.
- **Continue your work.** Persistent sessions, memory, and reusable skills keep
  context and workflows available between conversations.
- **Use real tools.** Work with files, execute terminal commands, browse the web,
  and connect additional capabilities through MCP and plugins.
- **Choose your model.** Configure supported cloud providers or compatible local
  model endpoints; keep provider credentials in your local configuration.
- **Organize ongoing tasks.** Delegate to subagents, schedule jobs, and manage
  separate profiles for different configurations and workspaces.
- **Connect messaging services.** Use the gateway with configured adapters such
  as Telegram, Discord, and Slack. Telegram's `/status` opens controls for status,
  stopping a turn, and pausing or resuming a loop.
- **Move from Hermes.** Preview and import conversations, compatible settings,
  memories, skills, custom prompts, and named profiles from Desktop Settings.
- **Pick your interface.** Use the same agent core from the desktop, CLI, Ink
  terminal UI, or web dashboard.

## Engineering workflow

Use `/zeus-engineering <task>` for a workflow that establishes a baseline,
implements the change, challenges failure cases, and reports the observed
results. In Desktop, open **Evidence** beside the coding workspace controls.

```sh
zeus verify --detect-only --json
zeus verify --status --json
zeus verify --capture-baseline --json
```

Detection and status do not execute a project recipe. Run the project's checks
before capturing a baseline; capture accepts current failures as well as passes.
Use `--session <name>` consistently when working outside an agent session.
`--status` exits zero only for current passing evidence. Clear a comparison
baseline with `zeus verify --clear-baseline`; check history is retained.

Receipts describe **local Git source contents**, including uncommitted edits.
They are not a guarantee of correctness and do not identify ignored dependencies,
remote services, or runtime configuration. Unsupported source layouts remain
unverified. A check's original result and its current freshness are separate.

Telegram control commands remain separate from an active agent's message queue.
Configured aliases follow the target command's busy policy; commands addressed
to another bot are ignored. Conversation text and filesystem paths stay text.
Status buttons are bound to the requesting user, chat, topic, and current
session. An expired panel or a panel from before `/new` cannot control a new session.

## Move from Hermes

Open **Settings → Move from Hermes**, select the destination Zeus profile, and
enter the Hermes home folder on the gateway computer (usually `~/.hermes`).
Scan the folder, review the categories and conflicts, then import your selection.

The importer preserves the source. Existing Zeus settings win, memories are
appended, and conflicting files and skills receive separate names. Conversations
receive stable imported IDs, so importing the same history again does not create
duplicates. Existing files that require updates are backed up, and each import
leaves a receipt in the selected Zeus profile. Restart Zeus after importing to
reload configuration and history.

API keys, login tokens, scheduled jobs, plugins, project pins, live processes,
and gateway connections require separate setup. Conversation text and tool
history transfer; attachments and external file references keep their original
references and may need their original files. Named profiles are imported from
the default Zeus profile. If Hermes changes during a scan or import, close it
and scan again.

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

The fork adds content-bound verification receipts, baseline comparisons,
workspace-bound goal delivery, an engineering workflow, a Hermes migration
workspace, its own visual identity
and namespace, isolated ZeusAgent state, source setup and launch tools, and
changes to command routing, retry handling, and Windows behavior. Core agent
capabilities build on Hermes.

This repository currently provides source builds, without signed installers or
a configured ZeusAgent release/update service. Migration is an explicit action
in Settings; importing history does not reconnect accounts or resume old jobs.

The original **MIT license** and copyright notice are preserved in
[LICENSE](LICENSE); fork provenance and attribution are recorded in
[NOTICE.md](NOTICE.md). Third-party dependencies retain their own licenses.
