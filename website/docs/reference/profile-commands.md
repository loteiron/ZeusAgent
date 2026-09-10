---
sidebar_position: 7
---

# Profile Commands Reference

This page covers all commands related to [ZeusAgent profiles](../user-guide/profiles.md). For general CLI commands, see [CLI Commands Reference](./cli-commands.md).

## `zeus profile`

```bash
zeus profile <subcommand>
```

Top-level command for managing profiles. Running `zeus profile` without a subcommand shows help.

| Subcommand | Description |
|------------|-------------|
| `list` | List all profiles. |
| `use` | Set the active (default) profile. |
| `create` | Create a new profile. |
| `describe` | Read or set a profile's description (used by the kanban orchestrator for routing). |
| `delete` | Delete a profile. |
| `show` | Show details about a profile. |
| `alias` | Regenerate the shell alias for a profile. |
| `rename` | Rename a profile. |
| `export` | Export a profile to a tar.gz archive. |
| `import` | Import a profile from a tar.gz archive. |
| `install` | Install a profile distribution from a git URL or local directory. See [Profile Distributions](../user-guide/profile-distributions.md). |
| `update` | Re-pull a distribution-managed profile and re-apply its bundle. |
| `info` | Show distribution metadata for a profile (origin URL, commit, last update). |

## `zeus profile list`

```bash
zeus profile list
```

Lists all profiles. The currently active profile is marked with `*`.

**Example:**

```bash
$ zeus profile list
  default
* work
  dev
  personal
```

No options.

## `zeus profile use`

```bash
zeus profile use <name>
```

Sets `<name>` as the active profile. All subsequent `zeus` commands (without `-p`) will use this profile.

| Argument | Description |
|----------|-------------|
| `<name>` | Profile name to activate. Use `default` to return to the base profile. |

**Example:**

```bash
zeus profile use work
zeus profile use default
```

## `zeus profile create`

```bash
zeus profile create <name> [options]
```

Creates a new profile.

| Argument / Option | Description |
|-------------------|-------------|
| `<name>` | Name for the new profile. Must be a valid directory name (alphanumeric, hyphens, underscores). |
| `--clone` | Copy `config.yaml`, `.env`, `SOUL.md`, and skills from the current profile. |
| `--clone-all` | Copy everything (config, memories, skills, cron, plugins) from the current profile. Excludes per-profile history: sessions, `state.db`, backups, state-snapshots, checkpoints. |
| `--clone-from <profile>` | Clone config/skills/SOUL from a specific profile instead of the current one. Implies `--clone` unless paired with `--clone-all`. |
| `--no-alias` | Skip wrapper script creation. |
| `--description "<text>"` | One- or two-sentence description of what this profile is good at. Used by the kanban orchestrator to route tasks based on role instead of profile name alone. Skip and add later via `zeus profile describe`. Persisted in `<profile_dir>/profile.yaml`. |
| `--no-skills` | Create an **empty** profile with zero bundled skills enabled. Writes a `.no-bundled-skills` marker into the profile so future `zeus update` runs won't re-seed the bundled set, and refuses to combine with `--clone`, `--clone-from`, or `--clone-all` (which would copy skills in anyway). Useful for narrow orchestrator profiles or sandbox profiles that should not inherit the full skill catalog. To toggle this on an already-created profile (including the default `~/.zeus`), use `zeus skills opt-out` / `zeus skills opt-in`. |

Creating a profile does **not** make that profile directory the default project/workspace directory for terminal commands. If you want a profile to start in a specific project, set `terminal.cwd` in that profile's `config.yaml`.

**Examples:**

```bash
# Blank profile — needs full setup
zeus profile create mybot

# Clone config only from current profile
zeus profile create work --clone

# Clone everything from current profile
zeus profile create backup --clone-all

# Clone config from a specific profile
zeus profile create work2 --clone-from work

# Clone everything from a specific profile
zeus profile create work2-backup --clone-from work --clone-all
```

## `zeus profile describe`

```bash
zeus profile describe [<name>] [options]
```

Read or set a profile's description. The description is consumed by the kanban orchestrator to route tasks based on what each profile is good at, rather than guessing from the profile name alone. Persisted in `<profile_dir>/profile.yaml` so it survives reboots and is shared with the gateway.

With no flags, prints the current description (or `(no description set for '<name>')` if empty).

| Argument / Option | Description |
|-------------------|-------------|
| `<name>` | Profile to describe. Required unless `--all --auto` is used. |
| `--text "<text>"` | Set the description to this exact text (user-authored). Overwrites any existing description. |
| `--auto` | Auto-generate a 1-2 sentence description via the auxiliary LLM, based on the profile's installed skills, configured model, and name. Configure the model under `auxiliary.profile_describer` in `config.yaml`. Auto-generated descriptions are marked `description_auto: true` so the dashboard can flag them for review. |
| `--overwrite` | With `--auto`, replace user-authored descriptions too (default: skip profiles whose description was set explicitly). |
| `--all` | With `--auto`, sweep every profile missing a description. |

**Examples:**

```bash
# Read the current description
zeus profile describe researcher

# Set it explicitly
zeus profile describe researcher --text "Reads source code and writes findings."

# Let the LLM generate one
zeus profile describe researcher --auto

# Fill in descriptions for every profile that doesn't have one
zeus profile describe --all --auto
```

## `zeus profile delete`

```bash
zeus profile delete <name> [options]
```

Deletes a profile and removes its shell alias.

| Argument / Option | Description |
|-------------------|-------------|
| `<name>` | Profile to delete. |
| `--yes`, `-y` | Skip confirmation prompt. |

**Example:**

```bash
zeus profile delete mybot
zeus profile delete mybot --yes
```

:::warning
This permanently deletes the profile's entire directory including all config, memories, sessions, and skills. The `default` profile (`~/.zeus`) cannot be deleted — use `zeus uninstall` to remove everything.
:::

## `zeus profile show`

```bash
zeus profile show <name>
```

Displays details about a profile including its home directory, configured model, gateway status, skills count, and configuration file status.

This shows the profile's ZeusAgent home directory, not the terminal working directory. Terminal commands start from `terminal.cwd` (or the launch directory on the local backend when `cwd: "."`).

| Argument | Description |
|----------|-------------|
| `<name>` | Profile to inspect. |

**Example:**

```bash
$ zeus profile show work
Profile: work
Path:    ~/.zeus/profiles/work
Model:   anthropic/claude-sonnet-4 (anthropic)
Gateway: stopped
Skills:  12
.env:    exists
SOUL.md: exists
Alias:   ~/.local/bin/work
```

## `zeus profile alias`

```bash
zeus profile alias <name> [options]
```

Regenerates the shell alias script at `~/.local/bin/<name>`. Useful if the alias was accidentally deleted or if you need to update it after moving your ZeusAgent installation.

| Argument / Option | Description |
|-------------------|-------------|
| `<name>` | Profile to create/update the alias for. |
| `--remove` | Remove the wrapper script instead of creating it. |
| `--name <alias>` | Custom alias name (default: profile name). |

**Example:**

```bash
zeus profile alias work
# Creates/updates ~/.local/bin/work

zeus profile alias work --name mywork
# Creates ~/.local/bin/mywork

zeus profile alias work --remove
# Removes the wrapper script
```

## `zeus profile rename`

```bash
zeus profile rename <old-name> <new-name>
```

Renames a profile. Updates the directory and shell alias.

| Argument | Description |
|----------|-------------|
| `<old-name>` | Current profile name. |
| `<new-name>` | New profile name. |

**Example:**

```bash
zeus profile rename mybot assistant
# ~/.zeus/profiles/mybot → ~/.zeus/profiles/assistant
# ~/.local/bin/mybot → ~/.local/bin/assistant
```

## `zeus profile export`

```bash
zeus profile export <name> [options]
```

Exports a profile as a compressed tar.gz archive — a portable snapshot you can back up, move to another machine, or hand to someone else. `auth.json` and `.env` are always excluded.

Also available in chat as [`/export`](./slash-commands.md), and in the desktop app via **⌘K → Export profile…** or a profile square's right-click menu. A desktop export additionally stages `desktop.json` (skin, light/dark mode, custom themes, rail color, window layout) into the archive.

| Argument / Option | Description |
|-------------------|-------------|
| `<name>` | Profile to export. |
| `-o`, `--output <path>` | Output file path (default: `<name>.tar.gz`). |

**Example:**

```bash
zeus profile export work
# Creates work.tar.gz in the current directory

zeus profile export work -o ./work-2026-03-29.tar.gz
```

See [Export and import a profile file](../user-guide/profile-distributions.md#export-and-import-a-profile-file) for exactly what lands in the archive and what to check before sending one to someone else.

## `zeus profile import`

```bash
zeus profile import <archive> [options]
```

Imports a profile from a tar.gz archive, as a new profile. Refuses to overwrite an existing profile, and cannot import as `default` (the built-in root profile) — pass `--name` in either case. A shell wrapper is created when the name doesn't collide with an existing command.

Also available in chat as [`/import`](./slash-commands.md), and in the desktop app via **⌘K → Import profile…** or the import button beside the profile rail's **+**. A desktop import also applies any bundled `desktop.json` overlay (theme, layout) and switches you into the new profile.

| Argument / Option | Description |
|-------------------|-------------|
| `<archive>` | Path to the tar.gz archive to import. |
| `--name <name>` | Name for the imported profile (default: inferred from archive). |

**Example:**

```bash
zeus profile import ./work-2026-03-29.tar.gz
# Infers profile name from the archive

zeus profile import ./work-2026-03-29.tar.gz --name work-restored
```

## Distribution commands

:::tip
**New to distributions?** Start with the [Profile Distributions user guide](../user-guide/profile-distributions.md) — it covers the why, when, and how with full examples. The sections below are a dry CLI reference for when you know what you want.
:::

Distributions turn a profile into a shareable, versioned artifact published
as a **git repository**. A recipient installs the distribution with a single
command and can update it in place later without touching their local
memories, sessions, or credentials.

`auth.json` and `.env` are never part of a distribution — they stay on the
installing user's machine.

The recipient's user data (memories, sessions, auth, their own edits to
`.env`) is always preserved across the initial install and subsequent
updates.

:::info
Two ways to share a profile, and they complement each other. `zeus profile export` / `import` (also `/export` and `/import` in chat) produce a **single file** — no repo, no manifest, and a desktop export carries your theme and layout too. Distribution (`install` / `update` / `info`) publishes a profile as a **git repo** so recipients can pull versioned updates later. Backup and restore is the export file's other job. See [Two ways to share a profile](../user-guide/profile-distributions.md#two-ways-to-share-a-profile).
:::

### `zeus profile install`

```bash
zeus profile install <source> [--name <name>] [--alias] [--force] [--yes]
```

Installs a profile distribution from a git URL or a local directory.

| Option | Description |
|--------|-------------|
| `<source>` | Git URL (`github.com/user/repo`, `https://...`, `git@...`, `ssh://`, `git://`) or a local directory containing `distribution.yaml` at its root. |
| `--name NAME` | Override the profile name from the manifest. |
| `--alias` | Also create a shell wrapper (e.g. `telemetry` → `zeus -p telemetry`). |
| `--force` | Overwrite an existing profile of the same name. User data is still preserved. |
| `-y`, `--yes` | Skip the manifest-preview confirmation prompt. |

The installer shows the manifest, lists required env vars, and warns about
cron jobs before asking for confirmation. Required env vars go into a
`.env.EXAMPLE` file you copy to `.env` and fill in.

**Examples:**

```bash
# Install from a GitHub repo (shorthand)
zeus profile install github.com/kyle/telemetry-distribution --alias

# Install from a full HTTPS git URL
zeus profile install https://github.com/kyle/telemetry-distribution.git

# Install from SSH
zeus profile install git@github.com:kyle/telemetry-distribution.git

# Install from a local directory during development
zeus profile install ./telemetry/
```

### `zeus profile update`

```bash
zeus profile update <name> [--force-config] [--yes]
```

Re-clones the distribution from its recorded source and applies updates.
Distribution-owned files (SOUL.md, skills/, cron/, mcp.json) are
overwritten; user data (memories, sessions, auth, .env) is never touched.

`config.yaml` is preserved by default to keep your local overrides.
Pass `--force-config` to reset it to the distribution's shipped config.

### `zeus profile info`

```bash
zeus profile info <name>
```

Prints the profile's distribution manifest — name, version, required
ZeusAgent version, author, env var requirements, the source URL/path, and
the `Installed:` timestamp recorded when the distribution was last
`install`-ed or `update`-d. Useful for checking what a shared profile
needs before installing it, and for spotting "this profile was installed
6 months ago and hasn't been updated."

`zeus profile list` also shows the distribution name and version in a
`Distribution` column, and `zeus profile show <name>` / `delete <name>`
surface the source URL so you can tell at a glance which profiles came
from a git repo vs. were created locally.

### Private distributions

A private git repository works as a distribution source with no extra
configuration — the install shells out to your normal `git` binary, so
whatever authentication your shell is already set up for (SSH key,
`git credential` helper, GitHub CLI's stored HTTPS credentials) applies
transparently.

```bash
# Uses your SSH key, the same as any other `git clone`
zeus profile install git@github.com:your-org/internal-assistant.git

# Uses your git credential helper
zeus profile install https://github.com/your-org/internal-assistant.git
```

If a clone prompts for credentials interactively in your terminal during
install, that prompt flows through. Set up your auth the way you'd
normally use `git clone` against the same repo first, then install.

### Distribution manifest (`distribution.yaml`)

Every distribution has a `distribution.yaml` at the root of its repository:

```yaml
name: telemetry
version: 0.1.0
description: "Compliance monitoring harness"
zeus_requires: ">=0.12.0"
author: "Your Name"
license: "MIT"
env_requires:
  - name: OPENAI_API_KEY
    description: "OpenAI API key"
    required: true
  - name: GRAPHITI_MCP_URL
    description: "Memory graph URL"
    required: false
    default: "http://127.0.0.1:8000/sse"
distribution_owned:   # optional; defaults to SOUL.md, config.yaml,
                      #   mcp.json, skills/, cron/, distribution.yaml
  - SOUL.md
  - skills/compliance/
  - cron/
```

`zeus_requires` supports `>=`, `<=`, `==`, `!=`, `>`, `<`, or a bare
version (treated as `>=`). Install fails with a clear error if the current
ZeusAgent version doesn't satisfy the spec.

`distribution_owned` is optional. If set, only those paths are replaced on
update; anything else in the profile stays user-owned. If omitted, the
defaults above apply.

### Publishing a distribution

Authoring a distribution is just a git push:

1. In your profile directory, create `distribution.yaml` with at least `name`
   and `version`.
2. Initialize a git repo (or use an existing one) and push to GitHub /
   GitLab / any host ZeusAgent can clone from.
3. Tell recipients to run `zeus profile install <your-repo-url>`.

Use git tags for versioned releases — recipients who clone `HEAD` get your
latest state, and you can always bump `version:` in the manifest.

## `zeus -p` / `zeus --profile`

```bash
zeus -p <name> <command> [options]
zeus --profile <name> <command> [options]
```

Global flag to run any ZeusAgent command under a specific profile without changing the sticky default. This overrides the active profile for the duration of the command.

| Option | Description |
|--------|-------------|
| `-p <name>`, `--profile <name>` | Profile to use for this command. |

**Examples:**

```bash
zeus -p work chat -q "Check the server status"
zeus --profile dev gateway start
zeus -p personal skills list
zeus -p work config edit
```

## `zeus completion`

```bash
zeus completion <shell>
```

Generates shell completion scripts. Includes completions for profile names and profile subcommands.

| Argument | Description |
|----------|-------------|
| `<shell>` | Shell to generate completions for: `bash`, `zsh`, or `fish`. |

**Examples:**

```bash
# Install completions
zeus completion bash >> ~/.bashrc
zeus completion zsh >> ~/.zshrc
zeus completion fish > ~/.config/fish/completions/zeus.fish

# Reload shell
source ~/.bashrc
```

After installation, tab completion works for:
- `zeus profile <TAB>` — subcommands (list, use, create, etc.)
- `zeus profile use <TAB>` — profile names
- `zeus -p <TAB>` — profile names

## See also

- [Profiles User Guide](../user-guide/profiles.md)
- [CLI Commands Reference](./cli-commands.md)
- [FAQ — Profiles section](./faq.md#profiles)
