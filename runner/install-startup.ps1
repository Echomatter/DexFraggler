param([switch]$Remove)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
if ($Remove) {
 $shortcutPath = Join-Path ([Environment]::GetFolderPath('Startup')) 'DexFraggler.lnk'
 if (Test-Path -LiteralPath $shortcutPath) {
  $shellObject = New-Object -ComObject WScript.Shell
  $shortcut = $shellObject.CreateShortcut($shortcutPath)
  if ($shortcut.TargetPath -ne (Join-Path $projectRoot 'desktop\DexFraggler.Tray.exe')) { throw 'This shortcut belongs to another project.' }
  Remove-Item -LiteralPath $shortcutPath
 }
 Write-Output 'Automatic startup disabled.'
} else {
 & (Join-Path $projectRoot 'desktop\install-shortcuts.ps1') -ProjectRoot $projectRoot
}
