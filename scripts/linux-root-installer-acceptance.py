#!/usr/bin/env python3
"""Exercise a rendered installer as root on a disposable native Ubuntu runner.

Uses the published package and runtime assets, real Unix accounts, real Node and
the real Zeus runtime. This script must never run on a user's workstation/server:
it temporarily owns /usr/local/bin/zeus and creates the zeususer account.
The hosted runner's /usr/local directory permissions are temporarily set to
stock root-owned 0755 permissions and restored after the fixture is removed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import pwd
import shutil
import signal
import stat
import subprocess
import sys
import tarfile
import tempfile
import time


ACCOUNT = "zeususer"
ACCOUNT_HOME = Path("/home/zeususer")
GLOBAL_COMMAND = Path("/usr/local/bin/zeus")
SYSTEM_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def digest(filename: Path) -> str:
    with filename.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest() if hasattr(hashlib, "file_digest") else hashlib.sha256(stream.read()).hexdigest()


def account() -> pwd.struct_passwd | None:
    try:
        return pwd.getpwnam(ACCOUNT)
    except KeyError:
        return None


class Acceptance:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.scratch = Path(tempfile.mkdtemp(prefix="zeus-root-install-", dir="/root"))
        self.public = Path(tempfile.mkdtemp(prefix="zeus-root-workspace-", dir="/tmp"))
        self.public.chmod(0o755)
        self.home = self.scratch / "root home"
        self.home.mkdir(mode=0o700)
        self.private_bin = self.scratch / "root Node bin"
        self.private_bin.mkdir()
        self.log = Path(str(args.output) + ".log")
        self.log.parent.mkdir(parents=True, exist_ok=True)
        self.environment = {
            "HOME": str(self.home), "USER": "root", "LOGNAME": "root",
            "PATH": f"{self.private_bin}:{SYSTEM_PATH}",
            "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TZ": "UTC", "TERM": "dumb",
            # None of root's runtime/profile overrides may reach the account.
            "ZEUS_HOME": str(self.home / "root-profile-must-not-be-used"),
            "XDG_DATA_HOME": str(self.home / "root-data-must-not-be-used"),
        }
        self.receipt = {
            "platform": Path("/etc/os-release").read_text(encoding="utf-8"),
            "installer_sha256": digest(args.installer),
            "before_sha256": digest(args.before),
            "checks": [],
            "passed": False,
        }
        self.fixture_uid: int | None = None
        self.global_created = False
        self.original_backups = set(GLOBAL_COMMAND.parent.glob(".zeus-npm-backup.*"))
        self.host_directories: list[tuple[Path, os.stat_result]] = []

    def prepare_system_directories(self) -> None:
        # GitHub's shared tool directory can be owned/writable by its runner
        # account. Keep the production guard intact: this disposable fixture
        # explicitly models root-owned system directories on a fresh VPS.
        for directory in [Path("/usr/local"), GLOBAL_COMMAND.parent]:
            require(not directory.is_symlink() and directory.is_dir(),
                    f"Refusing to alter a linked/non-directory system path: {directory}")
            self.host_directories.append((directory, directory.stat()))
        self.receipt["host_directory_fixture"] = [
            {"path": str(directory), "original_uid": original.st_uid,
             "original_gid": original.st_gid, "original_mode": oct(stat.S_IMODE(original.st_mode)),
             "test_uid": 0, "test_gid": 0, "test_mode": "0o755"}
            for directory, original in self.host_directories
        ]
        for directory, _ in self.host_directories:
            os.chown(directory, 0, 0)
            directory.chmod(0o755)

    def restore_system_directories(self) -> None:
        for directory, original in reversed(self.host_directories):
            require(not directory.is_symlink(), f"System fixture became a symbolic link: {directory}")
            current = directory.stat()
            require((current.st_dev, current.st_ino) == (original.st_dev, original.st_ino),
                    f"System fixture directory identity changed: {directory}")
            os.chown(directory, original.st_uid, original.st_gid)
            directory.chmod(stat.S_IMODE(original.st_mode))

    def run(self, command: list[str], *, cwd: Path | None = None,
            env: dict[str, str] | None = None, expected: int | None = 0,
            timeout: int = 1800) -> subprocess.CompletedProcess[str]:
        print("[Zeus root acceptance] " + json.dumps(command, ensure_ascii=False), flush=True)
        process = subprocess.Popen(
            command, cwd=cwd or self.scratch, env=env or self.environment,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", start_new_session=True,
        )
        timed_out = False
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(process.pid, signal.SIGTERM)  # windows-footgun: ok — root Ubuntu-only acceptance harness.
            try:
                stdout, stderr = process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)  # windows-footgun: ok — root Ubuntu-only acceptance harness.
                stdout, stderr = process.communicate()
        with self.log.open("a", encoding="utf-8") as stream:
            stream.write("\n$ " + json.dumps(command, ensure_ascii=False) + "\n")
            stream.write(stdout + stderr + f"\nExit: {process.returncode}\n")
        require(not timed_out, f"Command exceeded {timeout}s; see {self.log}")
        result = subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
        if expected is not None:
            require(result.returncode == expected, f"Expected exit {expected}, got {result.returncode}: {stdout[-6000:]}\n{stderr[-6000:]}")
        return result

    def as_user(self, command: list[str], *, cwd: Path | None = None,
                expected: int | None = 0, path: str | None = None) -> subprocess.CompletedProcess[str]:
        return self.run([
            "/usr/sbin/runuser", "-u", ACCOUNT, "--", "/usr/bin/env", "-i",
            f"HOME={ACCOUNT_HOME}", f"USER={ACCOUNT}", f"LOGNAME={ACCOUNT}",
            f"PATH={path or str(ACCOUNT_HOME / '.local/bin') + ':' + SYSTEM_PATH}",
            "LANG=C.UTF-8", "LC_ALL=C.UTF-8", "TZ=UTC", *command,
        ], cwd=cwd or self.public, expected=expected)

    def prepare_actual_assets(self) -> None:
        self.assets = self.scratch / "downloaded release"
        self.assets.mkdir()
        packages = list(self.args.assets.glob("loteiron-zeus-agent-*.tgz"))
        require(len(packages) == 1, "Provide exactly one actual published npm package")
        self.package = packages[0]
        self.npm_root = self.scratch / "npm/lib/node_modules/@loteiron/zeus-agent"
        self.npm_root.mkdir(parents=True)
        with tarfile.open(self.package, "r:gz") as archive:
            members = archive.getmembers()
            for member in members:
                components = Path(member.name).parts
                require(components and components[0] == "package" and ".." not in components,
                        "Unsafe npm archive path")
                require(member.isdir() or member.isfile(), "npm acceptance payload must contain only ordinary files")
                target = self.npm_root.joinpath(*components[1:])
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    source = archive.extractfile(member)
                    require(source is not None, "Missing npm archive file")
                    with source, target.open("wb") as destination:
                        shutil.copyfileobj(source, destination)
                    target.chmod(member.mode & 0o777)
        self.manifest = json.loads((self.npm_root / "linux-runtime-manifest.json").read_text(encoding="utf-8"))
        self.receipt.update({"version": self.manifest["version"], "commit": self.manifest["commit"], "package_sha256": digest(self.package)})
        shutil.copyfile(self.package, self.assets / self.package.name)
        for asset in [self.manifest["source"], self.manifest["uv"], *self.manifest["tools"].values()]:
            name = asset["file"]
            require(Path(name).name == name and name not in (".", ".."), "Invalid runtime asset name")
            source = self.args.assets / name
            require(digest(source) == asset["sha256"], f"Published asset hash mismatch: {name}")
            shutil.copyfile(source, self.assets / name)
        node = self.manifest["tools"]["node"]
        self.run(["/usr/bin/tar", "-xJf", str(self.assets / node["file"]), "-C", str(self.scratch), node["executable"]])
        shutil.copyfile(self.scratch / node["executable"], self.private_bin / "node")
        (self.private_bin / "node").chmod(0o755)
        self.root_node_sha = digest(self.private_bin / "node")
        self.run([str(self.private_bin / "node"), "--version"])
        GLOBAL_COMMAND.symlink_to(self.npm_root / "bin/zeus.mjs")
        (self.private_bin / "zeus").symlink_to(self.npm_root / "bin/zeus.mjs")
        self.global_created = True

    def verify_workspace(self, cwd: Path, expected_workspace: Path, *, root: bool) -> dict:
        invocation = [str(GLOBAL_COMMAND), "verify", "--status", "--json"]
        result = self.run(invocation, cwd=cwd, expected=1) if root else self.as_user(invocation, cwd=cwd, expected=1)
        observed = json.loads(result.stdout.strip())["verification"]
        require(Path(observed["workspace"]["root"]).resolve() == expected_workspace.resolve(),
                f"Caller workspace was lost: {observed}")
        return {"caller": str(cwd), "observed": observed["workspace"]["root"], "exit_code": result.returncode, "root_invocation": root}

    def execute(self) -> None:
        self.prepare_system_directories()
        self.prepare_actual_assets()
        before = self.run(["/bin/bash", str(self.args.before), "--assets", str(self.assets)], expected=2)
        require("Run as your normal user" in before.stderr, "Baseline must reproduce the user's root refusal")
        require(account() is None, "Old installer unexpectedly created an account")

        started = time.monotonic()
        self.run(["/bin/bash", str(self.args.installer), "--assets", str(self.assets)])
        installed = account()
        require(installed is not None and 1000 <= installed.pw_uid < 65534, "Installer must create an ordinary account")
        self.fixture_uid = installed.pw_uid
        require(installed.pw_dir == str(ACCOUNT_HOME), "Unexpected account home")
        groups = self.run(["/usr/bin/id", "-nG", ACCOUNT]).stdout.split()
        require(not {"sudo", "wheel", "admin", "docker", "lxd"}.intersection(groups), "Installer account gained privileged supplementary groups")
        password = self.run(["/usr/bin/passwd", "--status", ACCOUNT]).stdout.split()
        require(len(password) >= 2 and password[1] == "L", "Automatically created account must have a locked password")

        denied = self.as_user(["/usr/bin/env", "node", "--version"], path=str(self.private_bin), expected=126)
        require("Permission denied" in denied.stderr, "Fixture must reproduce the root-only Node access failure")
        require(digest(self.private_bin / "node") == self.root_node_sha, "Root's existing Node installation changed")
        require(not GLOBAL_COMMAND.is_symlink() and GLOBAL_COMMAND.stat().st_uid == 0, "System dispatcher must be a root-owned regular file")
        require(stat.S_IMODE(GLOBAL_COMMAND.stat().st_mode) & 0o022 == 0, "System dispatcher must not be writable by ordinary users")

        version = self.run([str(GLOBAL_COMMAND), "--version"])
        require(self.manifest["version"] in version.stdout, "Root dispatcher must launch the actual released Zeus")
        root_path_version = self.run(["/bin/bash", "-c", "zeus --version"])
        require(self.manifest["version"] in root_path_version.stdout, "Root's existing npm bin directory still shadows the usable command")
        user_version = self.as_user(["/bin/bash", "-lc", "zeus --version"])
        require(self.manifest["version"] in user_version.stdout, "New login must find zeus automatically")
        runtime = ACCOUNT_HOME / ".local/share/ZeusAgent/runtimes" / f"{self.manifest['version']}-{self.manifest['source']['sha256'][:12]}"
        ready = runtime / "ready.json"
        cli = ACCOUNT_HOME / ".local/bin/zeus"
        for owned in [cli, ready, runtime / "source" / self.manifest["source"]["root"] / ".zeus-runtime.json"]:
            require(owned.stat().st_uid == installed.pw_uid, f"Runtime file was not created by the ordinary account: {owned}")
        require(json.loads(ready.read_text(encoding="utf-8"))["commit"] == self.manifest["commit"], "Runtime commit differs from the published package")
        require(not (self.home / "root-profile-must-not-be-used").exists(), "Root profile override leaked across privilege boundary")
        require(not (self.home / "root-data-must-not-be-used").exists(), "Root runtime override leaked across privilege boundary")
        self.receipt["checks"].append({
            "name": "root-only VPS installation", "passed": True,
            "baseline_root_exit": before.returncode, "baseline_node_exit": denied.returncode,
            "account": ACCOUNT, "uid": installed.pw_uid, "groups": groups, "password_locked": True,
            "version": version.stdout.strip(), "cold_seconds": round(time.monotonic() - started, 3),
            "ordinary_runtime_owner": ready.stat().st_uid,
        })

        project = self.public / "caller project Türkçe & literal"
        project.mkdir()
        os.chown(project, installed.pw_uid, installed.pw_gid)
        self.as_user(["/usr/bin/git", "init", "--quiet"], cwd=project)
        observations = [self.verify_workspace(project, project, root=True), self.verify_workspace(project, project, root=False)]
        observations.append(self.verify_workspace(self.scratch, ACCOUNT_HOME, root=True))
        profile = ACCOUNT_HOME / ".bashrc"
        with profile.open("a", encoding="utf-8") as stream:
            stream.write("\n# Acceptance: preserve this user preference.\n")
        config = ACCOUNT_HOME / ".zeus/config.yaml"
        config.parent.mkdir(exist_ok=True)
        os.chown(config.parent, installed.pw_uid, installed.pw_gid)
        previous = config.read_bytes() if config.exists() else b""
        config.write_bytes(previous + b"\n# Acceptance: preserve this user configuration.\n")
        os.chown(config, installed.pw_uid, installed.pw_gid)
        unchanged = {filename: (digest(filename), filename.stat().st_ino, filename.stat().st_mtime_ns) for filename in [ready, config, profile, cli, GLOBAL_COMMAND, self.private_bin / "zeus"]}
        self.run(["/bin/bash", str(self.args.installer), "--user", ACCOUNT, "--assets", str(self.assets)])
        require(account().pw_uid == installed.pw_uid, "Repeat install replaced the existing account")
        for filename, (sha, inode, mtime) in unchanged.items():
            require(digest(filename) == sha, f"Repeat install changed existing state or command: {filename}")
            if filename == ready:
                require((filename.stat().st_ino, filename.stat().st_mtime_ns) == (inode, mtime), "Repeat install rebuilt the ready runtime")
        self.run([str(GLOBAL_COMMAND), "--version"])
        dispatcher = GLOBAL_COMMAND.read_bytes()
        unrelated = b"#!/bin/sh\n# An unrelated command must remain untouched.\nexit 43\n"
        GLOBAL_COMMAND.write_bytes(unrelated)
        conflict = self.run(["/bin/bash", str(self.args.installer), "--user", ACCOUNT, "--assets", str(self.assets)], expected=2)
        require(GLOBAL_COMMAND.read_bytes() == unrelated, "Installer replaced an unrelated system command")
        GLOBAL_COMMAND.write_bytes(dispatcher)
        self.receipt["checks"].append({
            "name": "reuse, caller directory and profile preservation", "passed": True,
            "workspaces": observations, "reused_account_uid": installed.pw_uid,
            "preserved": [str(filename) for filename in unchanged], "cached_runtime_reused": True,
            "unrelated_command_preserved": True, "unrelated_command_exit": conflict.returncode,
        })
        self.receipt["passed"] = True

    def cleanup(self) -> None:
        # All targets were absent at entry or created by mkdtemp. Verify the
        # account identity and literal home again before removing this fixture.
        installed = account()
        if installed is not None:
            require(installed.pw_dir == str(ACCOUNT_HOME) and 1000 <= installed.pw_uid < 65534,
                    "Refusing cleanup of an unexpected account/home")
            if self.fixture_uid is not None:
                require(installed.pw_uid == self.fixture_uid, "Fixture account identity changed")
            self.run(["/usr/sbin/userdel", ACCOUNT], expected=0)
            require(not ACCOUNT_HOME.is_symlink() and ACCOUNT_HOME.resolve() == Path("/home/zeususer"), "Unsafe fixture home cleanup")
            if ACCOUNT_HOME.exists():
                shutil.rmtree(ACCOUNT_HOME)
        if self.global_created and os.path.lexists(GLOBAL_COMMAND):
            GLOBAL_COMMAND.unlink()
        for backup in set(GLOBAL_COMMAND.parent.glob(".zeus-npm-backup.*")) - self.original_backups:
            require(backup.is_symlink() and backup.resolve() == self.npm_root / "bin/zeus.mjs", "Unexpected npm backup; refusing cleanup")
            backup.unlink()
        require(self.scratch.parent == Path("/root") and self.scratch.name.startswith("zeus-root-install-"), "Unsafe private fixture cleanup")
        require(self.public.parent == Path("/tmp") and self.public.name.startswith("zeus-root-workspace-"), "Unsafe public fixture cleanup")
        shutil.rmtree(self.scratch)
        shutil.rmtree(self.public)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("installer", "before", "assets", "output"):
        parser.add_argument(f"--{option}", type=lambda value: Path(value).resolve(), required=True)
    args = parser.parse_args()
    require(sys.platform == "linux" and os.geteuid() == 0, "Run as root on a disposable native Ubuntu runner")  # windows-footgun: ok — short-circuit Linux guard.
    require(Path("/etc/os-release").is_file() and 'ID=ubuntu' in Path("/etc/os-release").read_text(encoding="utf-8"), "Ubuntu runner required")
    require(account() is None and not ACCOUNT_HOME.exists(), "Refusing to alter a pre-existing zeususer account or home")
    require(not os.path.lexists(GLOBAL_COMMAND), "Refusing to alter a pre-existing system zeus command")
    acceptance = Acceptance(args)
    try:
        acceptance.execute()
    except BaseException as error:
        acceptance.receipt["error"] = str(error)
        raise
    finally:
        acceptance.receipt["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        args.output.write_text(json.dumps(acceptance.receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        try:
            acceptance.cleanup()
        finally:
            acceptance.restore_system_directories()
    print(json.dumps(acceptance.receipt, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
