"""Exercise installer PATH ownership against private real Windows registry keys."""

from pathlib import Path
import json
import os
import subprocess

import pytest


pytestmark = pytest.mark.windows_only
MODULE = Path(__file__).resolve().parents[1] / "apps/desktop/installer/cli-path.psm1"


def _probe(tmp_path: Path, body: str) -> dict:
    install_directory = tmp_path / "App folder Ω"
    launcher = install_directory / "bin" / "zeus.cmd"
    launcher.parent.mkdir(parents=True)
    launcher.write_text("@echo off", encoding="ascii")
    script = tmp_path / "probe.ps1"
    script.write_text(
        r'''
param([string]$ModulePath, [string]$InstallDirectory)
function Trace-Stage([string]$Stage) {
    [Console]::Error.WriteLine(("ZEUS_PATH_PROBE {0:o} {1}" -f [DateTime]::UtcNow, $Stage))
}
Trace-Stage "script entered"
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [Text.Encoding]::UTF8
Trace-Stage "module import begin"
Import-Module $ModulePath -Force
Trace-Stage "module import complete"
$PSModuleAutoLoadingPreference = 'None'
$testRoot = "Software\ZeusAgent\InstallerTests\" + [Guid]::NewGuid().ToString("N")
$environmentKey = "$testRoot\Environment"
$registrationKey = "$testRoot\Registration"
$envKey = [Microsoft.Win32.Registry]::CurrentUser.CreateSubKey($environmentKey)
Trace-Stage "private registry created"
$bin = [IO.Path]::Combine($InstallDirectory, "bin")
Trace-Stage "launcher fixture ready"
function Change([string]$Action) {
    Trace-Stage "$Action begin"
    Update-ZeusCliPath -Action $Action -InstallDirectory $InstallDirectory -EnvironmentKeyPath $environmentKey -RegistrationKeyPath $registrationKey
    Trace-Stage "$Action complete"
}
function Read-Path {
    $envKey.GetValue("Path", $null, [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
}
function Write-Result([hashtable]$Value) {
    # The fixture invokes Windows PowerShell/.NET Framework explicitly. Avoid
    # cold Utility module discovery for ConvertTo-Json after registry work.
    Trace-Stage "result serialization begin"
    [void][Reflection.Assembly]::Load('System.Web.Extensions, Version=4.0.0.0, Culture=neutral, PublicKeyToken=31bf3856ad364e35')
    $serializer = [System.Web.Script.Serialization.JavaScriptSerializer]::new()
    [Console]::WriteLine($serializer.Serialize($Value))
    Trace-Stage "result serialization complete"
}
try {
''' + body + r'''
} finally {
    Trace-Stage "cleanup begin"
    $envKey.Dispose()
    [Microsoft.Win32.Registry]::CurrentUser.DeleteSubKeyTree($testRoot, $false)
    Trace-Stage "cleanup complete"
}
''', encoding="utf-8-sig")
    try:
        result = subprocess.run(
            [str(Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"),
             "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script),
             "-ModulePath", str(MODULE), "-InstallDirectory", str(install_directory)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=45,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except subprocess.TimeoutExpired as exc:
        # TimeoutExpired's message omits captured output. Preserve the bounded
        # stage trace so CI can distinguish shell startup from registry work.
        trace = exc.stderr or b""
        if isinstance(trace, bytes):
            trace = trace.decode("utf-8", errors="replace")
        pytest.fail(f"Installer PATH probe exceeded 45s. Stage trace:\n{trace[-4000:] or '(script not entered)'}")
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-3000:]
    return json.loads(result.stdout.strip())


def test_install_repair_uninstall_preserves_long_path_and_later_user_edits(tmp_path: Path):
    result = _probe(tmp_path, r'''
    $before = "%SystemRoot%\System32;" + ((1..180 | ForEach-Object { "C:\Tool$_" }) -join ";")
    $envKey.SetValue("Path", $before, [Microsoft.Win32.RegistryValueKind]::ExpandString)
    Change "Install"
    $installed = Read-Path
    Change "Install"
    $repaired = Read-Path
    $envKey.SetValue("Path", "$repaired;C:\AddedLater", [Microsoft.Win32.RegistryValueKind]::ExpandString)
    Change "Uninstall"
    Write-Result @{ before=$before; installed=$installed; repaired=$repaired; after=(Read-Path); bin=$bin; kind=$envKey.GetValueKind("Path").ToString() }
''')
    assert len(result["before"]) > 1024
    assert result["installed"] == result["before"] + ";" + result["bin"]
    assert result["repaired"] == result["installed"]
    assert result["after"] == result["before"] + r";C:\AddedLater"
    assert result["kind"] == "ExpandString"


def test_uninstall_preserves_preexisting_entry_and_restores_missing_path(tmp_path: Path):
    result = _probe(tmp_path, r'''
    $before = "C:\Tools;" + $bin.ToUpperInvariant() + "\"
    $envKey.SetValue("Path", $before, [Microsoft.Win32.RegistryValueKind]::String)
    Change "Install"
    Change "Uninstall"
    $preserved = Read-Path
    $kind = $envKey.GetValueKind("Path").ToString()
    $envKey.DeleteValue("Path")
    Change "Install"
    $installed = Read-Path
    $discovery = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey($registrationKey, $true)
    $discovered = $discovery.GetValue("InstallDirectory")
    $discovery.SetValue("InstallDirectory", "C:\DifferentInstall")
    Change "Uninstall"
    $retained = $discovery.GetValue("InstallDirectory")
    $discovery.Dispose()
    Write-Result @{ before=$before; preserved=$preserved; kind=$kind; installed=$installed; bin=$bin; removed=$null -eq (Read-Path); discovered=$discovered; install=$InstallDirectory; retained=$retained }
''')
    assert result["preserved"] == result["before"]
    assert result["kind"] == "String"
    assert result["installed"] == result["bin"]
    assert result["removed"] is True
    assert result["discovered"] == result["install"]
    assert result["retained"] == r"C:\DifferentInstall"


def test_path_registration_does_not_require_management_module_autoload(tmp_path: Path):
    result = _probe(tmp_path, r'''
    $envKey.SetValue("Path", "C:\Tools", [Microsoft.Win32.RegistryValueKind]::String)
    $PSModuleAutoLoadingPreference = 'None'
    try {
        Change "Install"
        $installed = Read-Path
        Change "Uninstall"
        $after = Read-Path
    } finally {
        $PSModuleAutoLoadingPreference = 'All'
    }
    Write-Result @{ installed=$installed; after=$after; bin=$bin }
''')
    assert result["installed"] == "C:\\Tools;" + result["bin"]
    assert result["after"] == r"C:\Tools"
