"""Install this exact ZeusAgent source tree without downloading another agent repository."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parents[1]
UV_VERSION = "0.11.33"


def run(argv: list[str], *, env: dict[str, str] | None = None) -> None:
    subprocess.run(argv, cwd=ROOT, env=env, check=True)


def interpreter(home: Path) -> Path:
    return home / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def uv_command(state: Path) -> list[str]:
    found = shutil.which("uv")
    if found:
        return [found]
    bootstrap = state / "venvs" / "bootstrap"
    python = interpreter(bootstrap)
    if not python.exists():
        venv.create(bootstrap, with_pip=True)
    run([str(python), "-m", "pip", "install", f"uv=={UV_VERSION}"])
    return [str(python), "-m", "uv"]


def npm_command(npm: str, env: dict[str, str]) -> list[str]:
    """Resolve a bundled npm entry point so check and install cannot select different CLIs."""
    launcher = Path(npm).absolute()
    sibling_node = launcher.parent / ("node.exe" if os.name == "nt" else "node")
    node = str(sibling_node) if sibling_node.is_file() else shutil.which("node", path=env.get("PATH"))
    if not node:
        raise RuntimeError("Node.js was not found beside npm or on PATH. Install Node.js and reopen the terminal.")
    user_prefix = None
    if os.name == "nt" and sibling_node.is_file():
        from zeus_cli.npm_engine import managed_npm_prefix
        # The Windows installer shim forwards to a per-user npm after a global
        # upgrade. Honor its standard prefix without starting npm-prefix.js.
        # Managed runtimes have their own npmrc/prefix and must stay in that tree.
        if managed_npm_prefix(npm) is None:
            settings = {k.lower(): v for k, v in env.items()}
            prefix = settings.get("npm_config_prefix")
            if prefix:
                user_prefix = Path(prefix).expanduser()
            elif settings.get("appdata"):
                user_prefix = Path(settings["appdata"]) / "npm"
    # Unix symlinks point into npm/bin; Windows installers put npm.cmd beside
    # node_modules; Unix prefix wrappers use ../lib/node_modules. Do not execute
    # npm.cmd's config/prefix subprocess just to discover a version.
    for entry in dict.fromkeys((launcher.resolve(), launcher)):
        candidates = [entry.parent / "node_modules/npm/package.json",
                      entry.parent.parent / "lib/node_modules/npm/package.json"]
        if entry.name == "npm-cli.js":
            candidates.insert(0, entry.parent.parent / "package.json")
        if user_prefix is not None:
            candidates.insert(0, user_prefix / "node_modules/npm/package.json")
        for manifest in candidates:
            if not manifest.is_file():
                continue
            package = json.loads(manifest.read_text(encoding="utf-8"))
            if isinstance(package, dict) and package.get("name") == "npm":
                cli = manifest.parent / "bin/npm-cli.js"
                if not cli.is_file():
                    raise RuntimeError(f"Incomplete npm installation: {cli} is missing. Reinstall Node.js/npm.")
                return [node, str(cli)]
    raise RuntimeError(
        f"Cannot locate npm's installed package beside {npm}. "
        "Expose the Node.js installation's bin directory on PATH (instead of a manager shim), then rerun setup."
    )


_ENGINE_PROBE = """
const fs = require('node:fs');
const {createRequire} = require('node:module');
const manifest = process.argv[1];
const semver = createRequire(manifest)('semver');
const package = JSON.parse(fs.readFileSync(manifest, 'utf8'));
const engines = JSON.parse(process.argv[2]);
const actual = {node: process.versions.node, npm: package.version};
for (const name of ['node', 'npm']) {
  if (!semver.valid(actual[name])) throw new Error('Invalid installed ' + name + ' version');
  if (semver.validRange(engines[name]) === null) throw new Error('Invalid engines.' + name + ' range');
}
console.log(JSON.stringify({...actual, compatible:
  semver.satisfies(actual.node, engines.node, {includePrerelease: true}) &&
  semver.satisfies(actual.npm, engines.npm, {includePrerelease: true})}));
"""


def frontend_toolchain(env: dict[str, str], *, repair: bool) -> tuple[list[str], dict[str, str]]:
    """Read local versions with npm's semver library; never start npm during the check."""
    from zeus_constants import get_zeus_home, with_zeus_node_path
    from zeus_cli.npm_engine import is_ebadengine, maybe_repair_npm_engine

    try:
        package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        engines = package.get("engines") if isinstance(package, dict) else None
        if not isinstance(engines, dict) or not all(
            isinstance(engines.get(name), str) and engines[name].strip() for name in ("node", "npm")
        ):
            raise ValueError("package.json must declare engines.node and engines.npm")
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"Cannot read source toolchain requirements: {exc}. Extract the complete source package.") from exc
    env = with_zeus_node_path(env)
    npm = shutil.which("npm", path=env.get("PATH"))
    hint = (f"Required Node.js: {engines['node']}; npm: {engines['npm']}. "
            "For Node.js 24.14.1 with npm 11.11.0, run: npm install --global npm@11.17.0 "
            "(Windows PowerShell: npm.cmd install --global npm@11.17.0). "
            "Then rerun setup; existing Python packages and configuration are retained.")
    if not npm:
        raise RuntimeError(f"Node.js/npm was not found on PATH. Install Node.js and reopen the terminal. {hint}")
    print("Checking Node.js/npm compatibility before dependency installation...", flush=True)
    for attempt in range(2):
        try:
            command = npm_command(npm, env)
            manifest = Path(command[1]).parent.parent / "package.json"
            # npm lifecycle scripts must inherit the same Node that was checked.
            node_dir = str(Path(command[0]).parent)
            env = {**env, "PATH": os.pathsep.join([node_dir, *[
                p for p in env.get("PATH", "").split(os.pathsep) if p and p != node_dir
            ]])}
            # Version inspection does not need a caller's injected Node preload hooks.
            probe_env = {k: v for k, v in env.items() if k.upper() != "NODE_OPTIONS"}
            result = subprocess.run(
                [command[0], "--eval", _ENGINE_PROBE, str(manifest), json.dumps(engines)],
                cwd=ROOT, env=probe_env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15,
            )
            if result.returncode:
                raise RuntimeError((result.stderr or result.stdout).strip() or f"Node exited with {result.returncode}")
            actual = json.loads(result.stdout)
            if (not isinstance(actual, dict) or type(actual.get("compatible")) is not bool
                    or not all(isinstance(actual.get(name), str) and actual[name] for name in ("node", "npm"))):
                raise ValueError("Node returned an invalid version report")
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(f"Cannot inspect the local Node.js/npm installation: {exc}. {hint}") from exc
        print(f"Detected Node.js {actual['node']}; npm {actual['npm']} ({command[1]})", flush=True)
        if actual["compatible"]:
            return command, env
        output = ("npm error code EBADENGINE\nRequired: " + json.dumps(engines)
                  + "\nActual: " + json.dumps({name: actual[name] for name in ("node", "npm")}))
        if attempt == 0 and repair and is_ebadengine(output):
            print("Incompatible toolchain. Trying the ZeusAgent-managed runtime...", flush=True)
            get_zeus_home().mkdir(parents=True, exist_ok=True)
            repaired = maybe_repair_npm_engine(npm, output)
            if repaired:
                npm = repaired
                env = with_zeus_node_path(env)
                continue
        raise RuntimeError(f"Node.js/npm compatibility check failed:\n{output}\n{hint}")
    raise RuntimeError("Node.js/npm compatibility could not be established.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Install this ZeusAgent source package.")
    parser.add_argument("--web", action="store_true", help="Build the dashboard and terminal UI.")
    parser.add_argument("--desktop", action="store_true", help="Also build the Electron desktop app.")
    parser.add_argument("--dev", action="store_true", help="Install test and analysis dependencies.")
    parser.add_argument("--test-all", action="store_true", help="Install the complete locked Python CI test extras (implies --dev; no live services).")
    parser.add_argument("--check", action="store_true", help="Check prerequisites without installing packages or repairing runtimes.")
    args = parser.parse_args()
    if not (3, 11) <= sys.version_info < (3, 14):
        parser.error("Python 3.11, 3.12 or 3.13 is required.")
    if not (ROOT / "zeus_cli" / "main.py").is_file():
        parser.error("Extract the complete ZeusAgent source package before running setup.")
    sys.path.insert(0, str(ROOT))
    from zeus_constants import get_zeus_home
    state = get_zeus_home().expanduser().resolve()
    environment = state / "venvs" / "zeus-agent"
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    npm = None
    if args.web or args.desktop:
        try:
            npm, env = frontend_toolchain(env, repair=not args.check)
        except RuntimeError as exc:
            parser.error(str(exc))
    if args.check:
        print("ZeusAgent prerequisites verified. No dependencies installed.")
        return 0
    state.mkdir(parents=True, exist_ok=True)
    env["UV_PROJECT_ENVIRONMENT"] = str(environment)
    command = [*uv_command(state), "sync", "--python", sys.executable, "--locked",
               "--extra", "messaging", "--extra", "web", "--extra", "anthropic", "--extra", "acp"]
    if args.dev or args.test_all:
        # The media/provider contract tests load these optional SDKs without live calls.
        command += ["--extra", "dev", "--extra", "fal", "--extra", "wecom"]
    if args.test_all:
        for extra in ("all", "mistral", "modal", "daytona", "hindsight", "parallel-web"):
            command += ["--extra", extra]
    run(command, env=env)
    if npm is not None:
        # These are the upstream-reviewed, locked workspace lifecycle scripts.
        install = [*npm, "ci", "--no-audit", "--no-fund"]
        if not args.desktop:
            # A web/TUI install must not require Electron or its native PTY.
            install += ["--include-workspace-root"]
            for workspace in ("ui-tui", "web", "@zeus/ink", "@zeus/shared"):
                install += ["--workspace", workspace]
        run(install, env=env)
        run([*npm, "run", "build", "--workspace", "@zeus/ink"], env=env)
        run([*npm, "run", "build", "--workspace", "ui-tui"], env=env)
        run([*npm, "run", "build", "--workspace", "web"], env=env)
        if args.desktop:
            run([*npm, "run", "build", "--workspace", "apps/desktop"], env=env)
    print(f"\nZeusAgent ready. Source: {ROOT}")
    print("Configure: python scripts/launch_zeus.py setup")
    print("Chat:      python scripts/launch_zeus.py")
    print("Telegram:  python scripts/launch_zeus.py gateway run")
    print("Dashboard: python scripts/launch_zeus.py dashboard")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        print(f"Setup stopped (exit {exc.returncode}). Correct the reported error and rerun.", file=sys.stderr)
        raise SystemExit(exc.returncode)
    except OSError as exc:
        print(f"Setup could not continue: {exc}. Correct the error and rerun setup.", file=sys.stderr)
        raise SystemExit(1)
    except KeyboardInterrupt:
        print("Setup interrupted. Rerun the same command to resume installation.", file=sys.stderr)
        raise SystemExit(130)
