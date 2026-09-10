# Contributing to ZeusAgent

ZeusAgent is an independent, source-only fork of Hermes Agent. Work in the issue
tracker and pull requests of the repository from which you obtained this source;
Nous Research does not maintain this fork. Read [AGENTS.md](AGENTS.md) and the
area-specific instructions before changing code.

## Development setup

Use Python 3.11–3.13. The CI reference interpreter is 3.12. For JavaScript, use
the Node/npm ranges declared in `package.json`; install from the repository root.

```sh
python scripts/setup_zeus.py --test-all --web
python scripts/launch_zeus.py --help
```

`--test-all` installs the locked Python CI extras, including optional SDKs needed
by mocked provider tests. It does not configure accounts or call live services.
`--desktop` also builds Electron. Native dependency installation must succeed:
`npm ci --ignore-scripts` is not a valid substitute for a working desktop install.

## TDD and the development loop

These are working methods, not new runtime features:

1. State the behavior that must remain true and write one or two invariant tests.
2. Run the test against the faulty implementation and retain the actual failure.
3. Make the smallest relevant change; keep user edits and unrelated behavior intact.
4. Run the same test, nearby contracts, then the relevant broader suite.
5. Inspect the evidence. Separate a product defect, a broken fixture, an environment
   restriction and an untested integration; repeat as needed.

Do not relax approvals, SSRF checks, process guards or assertions to get a green
result. Do not fake the host OS. Run Windows/macOS cases on those operating systems.

## Tests

Use the canonical isolated Python runner, never a monolithic bare pytest invocation:

```sh
ZEUS_PYTHON="$HOME/.zeus/venvs/zeus-agent/bin/python" bash scripts/run_tests.sh -j 4 --file-retries 0
npm run typecheck --workspaces --if-present
npm run test --workspace ui-tui -- --maxWorkers=2
npm run test --workspace web -- --maxWorkers=2
npm run test --workspace tests-js -- --maxWorkers=2
npm run test:ui --workspace apps/desktop -- --maxWorkers=2
npm run test:desktop:platforms --workspace apps/desktop -- --maxWorkers=2
```

Adjust `ZEUS_PYTHON` for custom state paths; on Windows the interpreter ends in
`venvs/zeus-agent/Scripts/python.exe` and the shell runner requires Git Bash.
A repository-local `.venv` installed using the workflow's `uv sync` command is
detected automatically. Default discovery excludes integration, e2e and Docker
directories. Real provider and GUI flows need explicit, isolated test environments.

The sole active workflow is [zeus-ci.yml](.github/workflows/zeus-ci.yml).
The 32 upstream workflows remain in `.github/upstream-workflows/` for reference,
not execution. They are not drop-in workflows for a new account.

## Pull requests and review

Include the problem, red/green commands with exit statuses, the affected platforms,
compatibility impact and remaining limitations. Report failing, skipped and unrun
tests explicitly. No passing badge is a substitute for logs. Dependency changes
must update their lockfile and retain the bounds/pinning policy in AGENTS.md.
Never add API keys, cookies, user configuration, conversation exports or live databases.

Prefer plugins and skills to enlarging the core. Keep the existing trust model,
public contracts and prompt-cache invariants. For architectural background, the
[archived upstream guide](docs/UPSTREAM-CONTRIBUTING.md) retains the original
detailed material; its installer, maintainer and publishing instructions are historical.

## Security and publication

Follow [SECURITY.md](SECURITY.md) for private reports. Diagnostics must be reviewed
and redacted before sharing; a public paste service is not a prerequisite for help.
Run `python scripts/github_source.py check` before publishing source.
Keep [LICENSE](LICENSE) and [NOTICE.md](NOTICE.md) intact.
