"""The Windows hand-off keeps serving progress while its main thread blocks.

windows.ps1 answers /progress from a dedicated runspace precisely so the
window keeps moving through the long silent stretches (`zeus update`, pip,
the desktop rebuild) that made an 18-minute update look hung. This drives the
real script and polls the real listener; the posix half of the same contract
is covered in test_desktop_update_shim_progress.py.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from urllib.request import urlopen

import pytest

pytestmark = pytest.mark.windows_only

REPO_ROOT = Path(__file__).resolve().parent.parent
WINDOWS_UPDATE_PS1 = REPO_ROOT / "scripts" / "desktop-update" / "windows.ps1"


def _await_progress_url(process: subprocess.Popen, output_path: Path) -> str:
    # Host/module preparation is a fixture prerequisite, not a running updater.
    # Once prepared, the real listener still has the original 20-second budget.
    deadline = time.monotonic() + 45
    phase = "host preparation"
    text = ""
    while time.monotonic() < deadline:
        text = output_path.read_text(encoding="utf-8", errors="replace")
        if phase == "host preparation" and "ZEUS_PROGRESS_HOST ready" in text:
            phase = "listener startup"
            deadline = time.monotonic() + 20
        match = re.search(r"SELF-TEST: shim at (http://127\.0\.0\.1:\d+/)", text)
        if match:
            assert phase == "listener startup", "updater started before host preparation"
            return match.group(1)
        if process.poll() is not None:
            break
        time.sleep(0.1)
    raise AssertionError(f"Progress {phase} did not finish within its budget.\n{text[-8000:]}")


def _read_progress(url: str, deadline: float) -> dict[str, object]:
    """Poll /progress, retrying transient socket stalls until ``deadline``.

    A single slow answer from the PS runspace listener is NOT the bug this
    test guards (the listener can lose the CPU for seconds on a loaded CI
    runner while it still serves fine a moment later). One raw
    ``urlopen(timeout=5)`` propagating TimeoutError was exactly the Aug 2026
    flake (run 32440286339). Only a listener that stays unresponsive until
    the deadline fails the test.

    Per-attempt timeout is 1s, not 5s: a connection the kernel accepted into
    the backlog before the runspace was serving never gets answered, and a 5s
    wait on it burned half the readiness budget per attempt (two stale
    attempts = red, run 33591547099). The script's own readiness handshake
    now keeps that gap from reaching us, but the probe should not be able to
    lose the whole budget to one dead socket either way.
    """
    last_exc: Exception | None = None
    attempted = False
    while not attempted or time.monotonic() < deadline:
        attempted = True
        try:
            with urlopen(f"{url}progress", timeout=1) as response:
                return json.loads(response.read().decode("utf-8"))
        except (TimeoutError, OSError) as exc:  # transient stall — retry
            last_exc = exc
            time.sleep(0.1)
    raise AssertionError(
        f"/progress unresponsive until deadline (last error: {last_exc!r})"
    )


@pytest.mark.parametrize(
    ("slow_focus_compiler", "host_preparation_delay"),
    [(False, 0), (True, 0), (False, 21)],
    ids=["normal", "slow-focus", "slow-host"],
)
def test_progress_advances_while_the_orchestrator_blocks(
    tmp_path: Path, slow_focus_compiler: bool, host_preparation_delay: int,
) -> None:
    powershell = shutil.which("powershell.exe")
    assert powershell, "Windows updater tests require Windows PowerShell."

    output_path = tmp_path / "self-test-output.log"
    env = os.environ.copy()
    env["TEMP"] = str(tmp_path)
    env["TMP"] = str(tmp_path)
    # Generous hold: the assertions below must both land INSIDE it. 4s was
    # too tight for a slow runner — the second sample slid past the hold,
    # caught the cleared terminal state, and failed '' == 'Testing quiet
    # update' (PR #90358 rerun, Aug 2026). 10s left no headroom once
    # transient /progress retries entered the budget (publish wait ≤10s +
    # stability window + retry sleeps), so: 30s, and every sampling deadline
    # below is derived from the moment the held stage lands, keeping the
    # whole window comfortably inside the hold.
    env["ZEUS_SELFTEST_HOLD_SECONDS"] = "30"

    wrapper = tmp_path / "prepared-progress-host.ps1"
    wrapper.write_text(
        "param([string]$Target)\n"
        "[Console]::Error.WriteLine('ZEUS_PROGRESS_HOST preparing local modules')\n"
        f"[Threading.Thread]::Sleep({host_preparation_delay * 1000})\n"
        # Only OS modules are needed by this isolated self-test. The new
        # listener runspace inherits this same fixed, local module location.
        "$moduleRoot = [IO.Path]::Combine($PSHOME, 'Modules')\n"
        "$env:PSModulePath = $moduleRoot\n"
        "$management = [IO.Path]::Combine($moduleRoot, 'Microsoft.PowerShell.Management', 'Microsoft.PowerShell.Management.psd1')\n"
        "$utility = [IO.Path]::Combine($moduleRoot, 'Microsoft.PowerShell.Utility', 'Microsoft.PowerShell.Utility.psd1')\n"
        "Import-Module $management -ErrorAction Stop\n"
        "Import-Module $utility -ErrorAction Stop\n"
        "[Console]::Error.WriteLine('ZEUS_PROGRESS_HOST preparing child runspace')\n"
        "$rs = [runspacefactory]::CreateRunspace(); $rs.Open()\n"
        "$warmup = [powershell]::Create(); $warmup.Runspace = $rs\n"
        "try {\n"
        "  [void]$warmup.AddCommand('Import-Module').AddParameter('Name', $utility).Invoke()\n"
        "  if ($warmup.HadErrors) { throw 'Child runspace module preparation failed' }\n"
        "  $warmup.Commands.Clear()\n"
        "  [void]$warmup.AddCommand('ConvertTo-Json').AddParameter('InputObject', @{ready=$true}).AddParameter('Compress').Invoke()\n"
        "  if ($warmup.HadErrors) { throw 'Child runspace JSON preparation failed' }\n"
        "} finally { $warmup.Dispose(); $rs.Close(); $rs.Dispose() }\n"
        + (
            "function Add-Type {\n"
            "  if ($args -contains 'ZeusAgentHandoff') {\n"
            "    Write-Host 'SLOW-FOCUS-COMPILER-START'\n"
            "    Start-Sleep -Seconds 25\n"
            "  }\n"
            "  Microsoft.PowerShell.Utility\\Add-Type @args\n"
            "}\n"
            if slow_focus_compiler else ""
        )
        + "[Console]::Error.WriteLine('ZEUS_PROGRESS_HOST ready')\n"
        "& $Target -SelfTestUi -NoUi\n",
        encoding="utf-8",
    )
    command = [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
               str(wrapper), "-Target", str(WINDOWS_UPDATE_PS1)]

    with output_path.open("wb") as output:
        process = subprocess.Popen(
            command,
            stdout=output,
            stderr=subprocess.STDOUT,
            env=env,
            cwd=tmp_path,
        )

    try:
        shim_url = _await_progress_url(process, output_path)

        # The URL prints BEFORE the orchestrator publishes its held stage —
        # sampling immediately races the publish and can catch the page's
        # boot default instead ('ZeusAgent will open once done.' ==
        # 'Testing quiet update', PR #90358 first run). Wait for the held
        # stage to actually land, THEN start the stability window.
        held_stage = "Testing quiet update"
        publish_deadline = time.monotonic() + 10
        first = _read_progress(shim_url, publish_deadline)
        while first.get("message") != held_stage and time.monotonic() < publish_deadline:
            time.sleep(0.1)
            first = _read_progress(shim_url, publish_deadline)
        assert first["message"] == held_stage, first

        time.sleep(1.5)
        second = _read_progress(shim_url, time.monotonic() + 10)

        # The stage is whatever the orchestrator last published -- it must
        # reach the page verbatim and must not churn on its own.
        assert first["status"] == "running"
        assert first["message"]
        assert second["message"] == first["message"]
        # The main thread is asleep for the whole window above. If elapsed
        # only moved when the orchestrator published, it would be frozen here
        # -- which is what a stalled update looks like to the user.
        assert int(second["elapsed_seconds"]) > int(first["elapsed_seconds"])

        assert process.wait(timeout=60) == 0
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


def test_listener_deadline_is_not_extended_by_host_preparation(tmp_path: Path) -> None:
    powershell = shutil.which("powershell.exe")
    assert powershell
    script = tmp_path / "listener-never-starts.ps1"
    script.write_text(
        "[Console]::WriteLine('ZEUS_PROGRESS_HOST ready')\n"
        "[Threading.Thread]::Sleep(30000)\n",
        encoding="utf-8",
    )
    output_path = tmp_path / "blocked-listener.log"
    with output_path.open("wb") as output:
        process = subprocess.Popen(
            [powershell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script)],
            stdout=output, stderr=subprocess.STDOUT, cwd=tmp_path,
        )
    try:
        host_deadline = time.monotonic() + 45
        while "ZEUS_PROGRESS_HOST ready" not in output_path.read_text(encoding="utf-8", errors="replace"):
            assert process.poll() is None
            assert time.monotonic() < host_deadline
            time.sleep(0.05)
        started = time.perf_counter()
        with pytest.raises(AssertionError, match="listener startup did not finish"):
            _await_progress_url(process, output_path)
        elapsed = time.perf_counter() - started
        assert 19 <= elapsed < 25, f"listener did not retain its 20s budget: {elapsed:.3f}s"
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
