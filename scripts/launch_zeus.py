"""Launch the isolated ZeusAgent environment created by setup_zeus.py."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys


def desktop_command(root: Path, args: list[str], env: dict[str, str]) -> list[str]:
    desktop = root / "apps" / "desktop"
    setup_hint = "python scripts/setup_zeus.py --desktop"
    node = shutil.which("node", path=env.get("PATH"))
    if not node:
        raise RuntimeError(f"Install Node.js, then run: {setup_hint}")
    electron_cli = next((
        parent / "node_modules" / "electron" / "cli.js"
        for parent in (desktop, root)
        if (parent / "node_modules" / "electron" / "cli.js").is_file()
    ), None)
    if electron_cli is None:
        raise RuntimeError(f"Desktop dependencies are missing. Run: {setup_hint}")
    env.pop("ELECTRON_RUN_AS_NODE", None)
    # npm can leave cli.js installed even when Electron's binary download failed.
    # Ask the package's own resolver so hoisting, OS layout and overrides agree.
    try:
        probe = subprocess.run(
            [node, "-e", "process.stdout.write(require(process.argv[1]))", str(electron_cli.parent)],
            cwd=root, env=env, capture_output=True, text=True, encoding="utf-8", timeout=10,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Electron runtime check timed out. Run: {setup_hint}") from exc
    if probe.returncode or not probe.stdout.strip() or not Path(probe.stdout.strip()).is_file():
        raise RuntimeError(f"Electron runtime is incomplete. Run: {setup_hint}")
    if args[0] == "--desktop-dev":
        if len(args) > 1:
            raise RuntimeError("Use --desktop to pass Electron arguments; --desktop-dev takes no arguments.")
        npm = shutil.which("npm", path=env.get("PATH"))
        if not npm:
            raise RuntimeError(f"Install npm, then run: {setup_hint}")
        return [npm, "run", "dev", "--workspace", "apps/desktop"]
    if not all((desktop / "dist" / name).is_file() for name in ("electron-main.mjs", "index.html")):
        raise RuntimeError(f"Desktop build is missing. Run: {setup_hint}")
    # A stale development URL must not send the built app to a different renderer.
    env.pop("ZEUS_DESKTOP_DEV_SERVER", None)
    return [node, str(electron_cli), str(desktop), *args[1:]]


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    from zeus_constants import get_zeus_home, with_zeus_node_path
    state = get_zeus_home().expanduser().resolve()
    environment = state / "venvs" / "zeus-agent"
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    desktop = sys.argv[1:2] in (["--desktop"], ["--desktop-dev"])
    if not python.is_file():
        mode = "--desktop" if desktop else "--web"
        print(f"First run: python scripts/setup_zeus.py {mode}", file=sys.stderr)
        return 2
    env = with_zeus_node_path()
    env["ZEUS_HOME"] = str(state)
    env["ZEUS_PYTHON"] = str(python)
    env["PYTHONUTF8"] = "1"
    try:
        if desktop:
            env["ZEUS_DESKTOP_PYTHON"] = str(python)
            env["ZEUS_DESKTOP_ZEUS_ROOT"] = str(root)
            return subprocess.call(desktop_command(root, sys.argv[1:], env), cwd=root, env=env)
        # The absolute entry point leaves the user's working directory intact.
        return subprocess.call([str(python), str(root / "zeus"), *sys.argv[1:]], env=env)
    except (OSError, RuntimeError) as exc:
        print(f"ZeusAgent could not start: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
