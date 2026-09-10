param(
    [Parameter(Mandatory=$true)] [ValidateSet('Install', 'Uninstall')] [string]$Action,
    [Parameter(Mandatory=$true)] [string]$InstallDirectory
)
$ErrorActionPreference = 'Stop'
try {
    Import-Module (Join-Path $PSScriptRoot 'cli-path.psm1') -Force
    Update-ZeusCliPath -Action $Action -InstallDirectory $InstallDirectory
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class ZeusDesktopEnvironment {
    [DllImport("user32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    public static extern IntPtr SendMessageTimeout(IntPtr window, uint message, UIntPtr first, string second, uint flags, uint timeout, out UIntPtr result);
}
'@
    $result = [UIntPtr]::Zero
    [void][ZeusDesktopEnvironment]::SendMessageTimeout([IntPtr]0xffff, 0x1a, [UIntPtr]::Zero, 'Environment', 2, 5000, [ref]$result)
    Write-Output 'ZeusAgent command registration updated. Open a new terminal to use zeus.'
    exit 0
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
