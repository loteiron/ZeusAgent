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
In a CLI or terminal UI conversation, use `/evidence` to inspect the same
session's recorded results, freshness, output, and baseline comparisons.

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

In the terminal UI, Ctrl+C or double-Esc preserves a discarded draft for Up-arrow
recall, including multiline and pasted text. Discarded image attachments are
detached. Ctrl+C interrupts an active turn; from an empty idle composer it exits.

### Custom provider setup from Telegram

In a private chat with your Zeus bot, an explicitly authorized owner can configure
an OpenAI-compatible custom endpoint without opening the server terminal:

```text
/provider
/provider status
/provider set https://api.example.com/v1 your-model YOUR_API_KEY
```

The optional final argument selects `chat_completions` (default) or `responses`.
Use `none` instead of a key only for endpoints that require no authentication.
The URL is reached from the gateway computer, so `localhost` means that computer.

Setup applies to the next message in this chat and becomes the profile default
for new sessions. Stop an active turn with `/stop`, or let it finish, before
changing providers. This command saves the route; it does not test the endpoint.

Only explicitly listed private-chat owners (`allow_admin_from`, or `allow_from`
when no administrator policy is configured) can use this command. Group chats
and allow-all access cannot configure credentials. Keys go into the profile's
private `.env`; config stores a reference. Setup commands bypass agent turns,
transcripts, plugin hooks, and message queues. Zeus attempts to delete the setup
message from Telegram; if deletion fails, remove it yourself. Status hides keys.
This command supports custom providers only.

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

## Install on Windows

Download [setup.exe](https://github.com/loteiron/ZeusAgent/releases/download/v0.22.0/setup.exe)
for Windows x64. The per-user installer adds Desktop shortcuts and the `zeus`
command to your user PATH. Open a **new** CMD or PowerShell window after installation:

```sh
zeus setup
zeus
zeus --desktop
```

Run `zeus` from any project directory; that directory remains the agent's working
directory. The installer includes the reviewed Zeus source, prebuilt interfaces,
and checksum-pinned portable Git Bash, Node.js, ripgrep, and uv. First launch
downloads Python 3.12.12 and the locked Python dependencies into an isolated,
versioned runtime. Existing Python and Node installations are not required.
Internet access is required for this first setup and for hosted model providers.

The Windows installer is currently unsigned. Its SHA-256 checksum is published
with the [release assets](https://github.com/loteiron/ZeusAgent/releases/tag/v0.22.0).

## Install on Ubuntu Linux

For a server or terminal-only installation, run this from your current account,
including a root SSH session. No manual user creation or `su` is needed:

```sh
curl -fsSL https://raw.githubusercontent.com/loteiron/ZeusAgent/main/install.sh | bash
zeus setup
zeus
```

The bootstrap verifies the release installer's SHA-256 before running it. Root
installation makes `zeus` available immediately; a normal user may need to open
a new terminal after the first installation.

For Ubuntu 22.04 or 24.04 on x86_64, download the
[desktop .deb](https://github.com/loteiron/ZeusAgent/releases/download/v0.22.0/ZeusAgent-0.22.0-linux-x64.deb)
and install it from your download directory:

```sh
sudo apt install ./ZeusAgent-0.22.0-linux-x64.deb
zeus setup
zeus
zeus --desktop
```

APT installs the desktop dependencies, Git and ripgrep. The package adds an app
menu entry and `/usr/bin/zeus`, available from any project directory. Run Zeus as
your normal user. First launch sets up checksum-pinned Node.js, uv, Python 3.12.12
and the locked Python dependencies in your own versioned runtime. It does not
require a pre-existing Python or Node installation and needs internet access for
the first setup. Desktop and the command reuse this runtime.

For a terminal installation without Desktop or a pre-existing npm installation:

```sh
curl -fL --proto '=https' --proto-redir '=https' -o install-linux.sh https://github.com/loteiron/ZeusAgent/releases/download/v0.22.0/install-linux.sh
bash install-linux.sh
# Open a new terminal, then:
zeus setup
zeus
```

The installer verifies the release archive and private Node runtime, installs a
launcher in `~/.local/bin`, and adds that directory to supported shell profiles.
On a root SSH session, the same command installs missing system dependencies,
uses the ordinary sudo caller or creates/reuses `zeususer`, and completes setup
under that account. No password or sudo privileges are added to a newly created
account. A root-owned `/usr/local/bin/zeus` command automatically runs Zeus as
that user; use `zeus setup` and `zeus` directly. If the current directory is
inaccessible to that user, the command starts in their home directory and tells
you. Pass `--user NAME` to select an existing ordinary account explicitly.

Normal-user installation uses `sudo` only for missing Ubuntu dependencies. An
old global Zeus npm symlink is backed up when the root dispatcher replaces it;
unrelated launchers are preserved. `--no-modify-path` skips shell-profile edits.
Runtime files live under `${XDG_DATA_HOME:-~/.local/share}/ZeusAgent`;
conversations and settings live separately in the installation user's `~/.zeus`.

### Run alongside Hermes

Use a separate Zeus dashboard listener, including with the existing v0.22.0
release package:

```sh
zeus dashboard --host 127.0.0.1 --port 9129 --no-open
```

The current source also defaults to dashboard port `9129` and API server port
`8742`. Explicit port options still take precedence, including `--port 0` for
automatic dashboard port allocation. To use `8742` with an older packaged
runtime, set `platforms.api_server.port: 8742` in Zeus's `config.yaml` before
enabling that optional API adapter.

Telegram uses its own bot token and outbound polling, so it requires no inbound
TCP port. Once configured through `zeus setup`, keep it running across SSH
disconnects and reboots with:

```sh
zeus gateway install --start-now --start-on-login
zeus gateway status
```

Model-provider URLs are independent of these listeners. An existing OmniRoute
service can continue to serve both agents at its configured address.

## Install the command with npm

With Node.js 22.22 or later, install the same release directly from GitHub:

```sh
npm install --global https://github.com/loteiron/ZeusAgent/releases/download/v0.22.0/loteiron-zeus-agent-0.22.0.tgz
zeus setup
zeus
```

The npm package supports Windows x64 and Linux x64. Its first run downloads and
verifies the matching runtime and tools. Linux requires system Git and ripgrep
(`sudo apt install git ripgrep` on Ubuntu). `zeus --desktop` opens Desktop when
its Windows setup or Linux `.deb` is installed. The command preserves arguments
and the caller's project directory. This installation URL does not require an npm
registry account or a separately published registry package.

Install a newer release through its setup, `.deb`, terminal installer or npm asset. Packaged runtimes refuse
in-place source updates; configuration and conversations remain in your Zeus
home directory. Uninstalling Desktop removes its command registration and keeps
user data and versioned runtime caches.

## Run from source

Download or clone the complete repository, then run the following commands from
its root directory. Source installation also supports Linux and macOS.

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

## Local or custom model endpoints

Start an OpenAI-compatible model server and load a model before connecting.
In Desktop, open **Settings → Providers → API Keys → Local / custom endpoint**.
Enter the server's API base URL, such as `http://127.0.0.1:8000/v1`, and an API key
only if that server requires one. Select **Connect**.

ZeusAgent checks the endpoint, discovers its advertised models at `/v1/models`,
and saves the first available model with the URL and optional key. If the server
advertises no models, load one in the server and try again. The server must be
reachable from the machine running the ZeusAgent backend; with a remote backend,
`127.0.0.1` refers to that remote machine.

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

Windows releases provide an unsigned setup executable; Ubuntu releases provide
a `.deb` and terminal installer. A shared npm launcher supports both platforms.
macOS uses source installation. Install updates from ZeusAgent's release
assets. Automatic upstream replacement is disabled for packaged runtimes.
Migration is an explicit action in Settings; importing history does not reconnect
accounts or resume old jobs.

The original **MIT license** and copyright notice are preserved in
[LICENSE](LICENSE); fork provenance and attribution are recorded in
[NOTICE.md](NOTICE.md). Third-party dependencies retain their own licenses.
