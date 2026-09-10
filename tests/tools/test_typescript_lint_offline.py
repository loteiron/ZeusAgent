"""Optional post-write lint must neither fetch packages nor hide real diagnostics."""

from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import shutil
import threading

import pytest

from tools.environments.local import LocalEnvironment
from tools.file_operations import ShellFileOperations


@pytest.fixture
def offline_workspace(tmp_path):
    requests = []

    class Registry(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error":"package is not installed"}')

        def log_message(self, *_args):
            pass

    executable_dir = tmp_path / "executables"
    executable_dir.mkdir()
    for name in ("node", "npx"):
        executable = shutil.which(name)
        if executable is None:
            pytest.skip(f"Real {name} is required for the npm integration contract")
        (executable_dir / name).symlink_to(executable)
    project = tmp_path / "project"
    project.mkdir()
    (project / "package.json").write_text('{"name":"lint-contract","version":"1.0.0"}')
    server = HTTPServer(("127.0.0.1", 0), Registry)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02})
    thread.start()
    env = LocalEnvironment(cwd=str(project), env={
        "PATH": f"{executable_dir}:/usr/bin:/bin",
        "npm_config_cache": str(tmp_path / "npm-cache"),
        "npm_config_registry": f"http://127.0.0.1:{server.server_port}",
        "npm_config_fetch_retries": "0",
        "npm_config_fetch_timeout": "2000",
        "npm_config_update_notifier": "false",
    })
    try:
        yield project, ShellFileOperations(env), requests
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()
        assert not thread.is_alive()


@pytest.mark.linux_only
def test_missing_typescript_does_not_fetch_or_fail_a_verified_write(offline_workspace):
    project, operations, requests = offline_workspace
    target = project / "hello.ts"
    result = operations.write_file(str(target), "export const ok = true;\n")

    assert requests == [], "A file write must not fetch a compiler from the registry"
    assert result.error is None
    assert result.verified is True
    assert target.read_text() == "export const ok = true;\n"
    assert result.lint["status"] == "skipped"
    assert "not usable" in result.lint["message"]
    assert not (project / "node_modules").exists()


@pytest.mark.linux_only
def test_installed_compiler_diagnostics_survive_offline_lint(offline_workspace):
    project, operations, requests = offline_workspace
    binary = project / "node_modules" / ".bin" / "tsc"
    binary.parent.mkdir(parents=True)
    # An actual local executable exercises npm's resolution, arguments and exit
    # transport. TypeScript's own parser is outside this subprocess contract.
    binary.write_text(
        "#!/usr/bin/env node\n"
        "require('fs').writeFileSync('compiler-args.json', JSON.stringify(process.argv.slice(2)));\n"
        "console.log('error TS2322: number is not assignable to string');\n"
        "process.exit(2);\n"
    )
    binary.chmod(0o755)
    target = project / "bad.ts"
    result = operations.write_file(str(target), "export const value: string = 42;\n")

    assert requests == []
    assert result.error is None and result.verified is True
    assert result.lint["status"] == "error"
    assert "TS2322" in result.lint["output"]
    assert json.loads((project / "compiler-args.json").read_text()) == ["--noEmit", str(target)]
