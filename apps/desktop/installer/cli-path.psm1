Set-StrictMode -Version Latest

function ConvertTo-ComparablePath([string]$Entry) {
    return [Environment]::ExpandEnvironmentVariables($Entry.Trim().Trim('"')).TrimEnd([char[]]'\/')
}

function Update-ZeusCliPath {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)] [ValidateSet('Install', 'Uninstall')] [string]$Action,
        [Parameter(Mandatory=$true)] [string]$InstallDirectory,
        [string]$EnvironmentKeyPath = 'Environment',
        [string]$RegistrationKeyPath = 'Software\ZeusAgent\DesktopCLI'
    )

    $directory = [IO.Path]::Combine([IO.Path]::GetFullPath($InstallDirectory), 'bin')
    $comparable = ConvertTo-ComparablePath $directory
    $hasher = [Security.Cryptography.SHA256]::Create()
    try {
        $identity = ([BitConverter]::ToString($hasher.ComputeHash([Text.Encoding]::UTF8.GetBytes($comparable.ToUpperInvariant())))).Replace('-', '')
    } finally { $hasher.Dispose() }
    $ownerPath = "$RegistrationKeyPath\$identity"
    $registry = [Microsoft.Win32.Registry]::CurrentUser
    $environment = $registry.CreateSubKey($EnvironmentKeyPath)
    $owner = $registry.OpenSubKey($ownerPath, $true)
    try {
        $raw = $environment.GetValue('Path', $null, [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
        $exists = $null -ne $raw
        $current = if ($exists) { [string]$raw } else { '' }
        $kind = if ($exists) { $environment.GetValueKind('Path') } else { [Microsoft.Win32.RegistryValueKind]::ExpandString }
        if ($kind -notin @([Microsoft.Win32.RegistryValueKind]::String, [Microsoft.Win32.RegistryValueKind]::ExpandString)) {
            throw 'The user PATH registry value has an unsupported type.'
        }
        $entries = @($current.Split([char]';'))
        $matches = @($entries | Where-Object { [string]::Equals((ConvertTo-ComparablePath $_), $comparable, [StringComparison]::OrdinalIgnoreCase) })

        if ($Action -eq 'Install') {
            if (-not [IO.File]::Exists([IO.Path]::Combine($directory, 'zeus.cmd'))) {
                throw 'The installed ZeusAgent command launcher is missing.'
            }
            if ($null -eq $owner) { $owner = $registry.CreateSubKey($ownerPath) }
            if ($matches.Count -eq 0) {
                $after = if ($current) { "$current;$directory" } else { $directory }
                $owner.SetValue('PathBefore', $current, [Microsoft.Win32.RegistryValueKind]::String)
                $owner.SetValue('PathBeforeExists', [int]$exists, [Microsoft.Win32.RegistryValueKind]::DWord)
                $owner.SetValue('PathBeforeKind', $kind.ToString(), [Microsoft.Win32.RegistryValueKind]::String)
                $owner.SetValue('PathAfter', $after, [Microsoft.Win32.RegistryValueKind]::String)
                $owner.SetValue('PathAdded', 1, [Microsoft.Win32.RegistryValueKind]::DWord)
                $environment.SetValue('Path', $after, $kind)
            } elseif ($null -eq $owner.GetValue('PathAdded', $null)) {
                # An entry predating this installer belongs to the user.
                $owner.SetValue('PathAdded', 0, [Microsoft.Win32.RegistryValueKind]::DWord)
            }
            $owner.SetValue('Directory', $directory, [Microsoft.Win32.RegistryValueKind]::String)
            $discovery = $registry.CreateSubKey($RegistrationKeyPath)
            try {
                $discovery.SetValue('InstallDirectory', [IO.Path]::GetFullPath($InstallDirectory), [Microsoft.Win32.RegistryValueKind]::String)
            } finally { $discovery.Dispose() }
            return
        }

        if ($null -eq $owner) { return }
        if ([int]$owner.GetValue('PathAdded', 0) -eq 1 -and $matches.Count -gt 0) {
            if ($current -ceq [string]$owner.GetValue('PathAfter', '') -and $kind.ToString() -eq [string]$owner.GetValue('PathBeforeKind', '')) {
                if ([int]$owner.GetValue('PathBeforeExists', 0) -eq 1) {
                    $beforeKind = [Microsoft.Win32.RegistryValueKind]([string]$owner.GetValue('PathBeforeKind'))
                    $environment.SetValue('Path', [string]$owner.GetValue('PathBefore', ''), $beforeKind)
                } else {
                    $environment.DeleteValue('Path', $false)
                }
            } else {
                # Preserve additions and edits made after installation. Never
                # replace the whole PATH with an old snapshot in that case.
                $remaining = @($entries | Where-Object { -not [string]::Equals((ConvertTo-ComparablePath $_), $comparable, [StringComparison]::OrdinalIgnoreCase) })
                $environment.SetValue('Path', ($remaining -join ';'), $kind)
            }
        }
        $owner.Dispose()
        $owner = $null
        $registry.DeleteSubKeyTree($ownerPath, $false)
        $discovery = $registry.OpenSubKey($RegistrationKeyPath, $true)
        if ($null -ne $discovery) {
            try {
                $installed = [string]$discovery.GetValue('InstallDirectory', '')
                if ([string]::Equals($installed, [IO.Path]::GetFullPath($InstallDirectory), [StringComparison]::OrdinalIgnoreCase)) {
                    $discovery.DeleteValue('InstallDirectory', $false)
                }
            } finally { $discovery.Dispose() }
        }
    } finally {
        if ($null -ne $owner) { $owner.Dispose() }
        $environment.Dispose()
    }
}

Export-ModuleMember -Function Update-ZeusCliPath
