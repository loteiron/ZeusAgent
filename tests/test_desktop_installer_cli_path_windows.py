"""Exercise installer PATH ownership against private real Windows registry keys."""

from pathlib import Path
import json
import os
import subprocess

import pytest


pytestmark = pytest.mark.windows_only
MODULE = Path(__file__).resolve().parents[1] / "apps/desktop/installer/cli-path.psm1"


def _probe(tmp_path: Path, body: str) -> dict:
    script = tmp_path / "probe.ps1"
    script.write_text(
        r'''
param([string]$ModulePath, [string]$InstallDirectory)
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [Text.Encoding]::UTF8
Import-Module $ModulePath -Force
$testRoot = "Software\ZeusAgent\InstallerTests\" + [Guid]::NewGuid().ToString("N")
$environmentKey = "$testRoot\Environment"
$registrationKey = "$testRoot\Registration"
$envKey = [Microsoft.Win32.Registry]::CurrentUser.CreateSubKey($environmentKey)
$bin = Join-Path $InstallDirectory "bin"
New-Item -ItemType Directory -Path $bin -Force | Out-Null
Set-Content -LiteralPath (Join-Path $bin "zeus.cmd") -Value "@echo off" -Encoding Ascii
function Change([string]$Action) {
    Update-ZeusCliPath -Action $Action -InstallDirectory $InstallDirectory -EnvironmentKeyPath $environmentKey -RegistrationKeyPath $registrationKey
}
function Read-Path {
    $envKey.GetValue("Path", $null, [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
}
try {
''' + body + r'''
} finally {
    $envKey.Dispose()
    [Microsoft.Win32.Registry]::CurrentUser.DeleteSubKeyTree($testRoot, $false)
}
''', encoding="utf-8-sig")
    result = subprocess.run(
        [str(Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"),
         "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script),
         "-ModulePath", str(MODULE), "-InstallDirectory", str(tmp_path / "App folder Ω")],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=45,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
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
    @{ before=$before; installed=$installed; repaired=$repaired; after=(Read-Path); bin=$bin; kind=$envKey.GetValueKind("Path").ToString() } | ConvertTo-Json -Compress
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
    @{ before=$before; preserved=$preserved; kind=$kind; installed=$installed; bin=$bin; removed=$null -eq (Read-Path); discovered=$discovered; install=$InstallDirectory; retained=$retained } | ConvertTo-Json -Compress
''')
    assert result["preserved"] == result["before"]
    assert result["kind"] == "String"
    assert result["installed"] == result["bin"]
    assert result["removed"] is True
    assert result["discovered"] == result["install"]
    assert result["retained"] == r"C:\DifferentInstall"
