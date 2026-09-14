[CmdletBinding(SupportsShouldProcess = $true)]
param([Parameter(Mandatory = $true)][string]$ProjectRoot)
$ErrorActionPreference = 'Stop'
$resolvedRoot = [System.IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\', '/')
if (-not (Test-Path -LiteralPath $resolvedRoot -PathType Container)) { throw 'The project directory does not exist.' }
$trayPath = Join-Path $resolvedRoot 'desktop\DexFraggler.Tray.exe'
if (-not (Test-Path -LiteralPath $trayPath -PathType Leaf)) { throw 'Install desktop\DexFraggler.Tray.exe in this project before creating shortcuts.' }
$desktopDirectory = [Environment]::GetFolderPath('DesktopDirectory')
$startupDirectory = [Environment]::GetFolderPath('Startup')
$desktopLink = Join-Path $desktopDirectory 'DexFraggler.lnk'
$startupLink = Join-Path $startupDirectory 'DexFraggler.lnk'
$legacyLink = Join-Path $startupDirectory 'DexFraggler background runner.lnk'
$shellObject = New-Object -ComObject WScript.Shell
function Test-SameProjectShortcut($Shortcut) {
    $target = [string]$Shortcut.TargetPath
    try {
        $absoluteTarget = [System.IO.Path]::GetFullPath($target)
        if ($absoluteTarget.Equals($trayPath, [StringComparison]::OrdinalIgnoreCase) -or $absoluteTarget.StartsWith($resolvedRoot + '\', [StringComparison]::OrdinalIgnoreCase)) { return $true }
    } catch { }
    $escaped = [regex]::Escape($resolvedRoot)
    return [regex]::IsMatch([string]$Shortcut.Arguments, '(?i)(?:^|[\s"=])' + $escaped + '(?:[\\/]|["\s]|$)')
}
foreach ($linkPath in @($desktopLink, $startupLink)) {
    if (Test-Path -LiteralPath $linkPath) {
        $existing = $shellObject.CreateShortcut($linkPath)
        try { if (-not (Test-SameProjectShortcut $existing)) { throw "The existing shortcut belongs to another project: $linkPath" } }
        finally { [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($existing) }
    }
}
$legacyOwned = $false
if (Test-Path -LiteralPath $legacyLink) {
    $legacy = $shellObject.CreateShortcut($legacyLink)
    try { $legacyOwned = Test-SameProjectShortcut $legacy }
    finally { [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($legacy) }
}
foreach ($linkPath in @($desktopLink, $startupLink)) {
    if ($PSCmdlet.ShouldProcess($linkPath, 'Create the DexFraggler tray shortcut')) {
        $shortcut = $shellObject.CreateShortcut($linkPath)
        try {
            $shortcut.TargetPath = $trayPath
            $shortcut.Arguments = '--root "' + $resolvedRoot + '"'
            if ($linkPath -eq $desktopLink) { $shortcut.Arguments += ' --open' }
            $shortcut.WorkingDirectory = $resolvedRoot
            $shortcut.IconLocation = $trayPath + ',0'
            $shortcut.Description = 'DexFraggler waveform table and background computing controls'
            $shortcut.WindowStyle = 7
            $shortcut.Save()
        } finally { [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($shortcut) }
    }
}
$legacyRemoved = $false
if ($legacyOwned -and $PSCmdlet.ShouldProcess($legacyLink, "Remove this project's obsolete background-runner shortcut")) {
    Remove-Item -LiteralPath $legacyLink -Force
    $legacyRemoved = $true
}
[void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($shellObject)
@{ projectRoot=$resolvedRoot; executable=$trayPath; desktopShortcut=$desktopLink; startupShortcut=$startupLink; obsoleteShortcutRemoved=$legacyRemoved; processLaunched=$false } | ConvertTo-Json
