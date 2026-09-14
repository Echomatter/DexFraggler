param([switch]$Remove)
$taskRoot = Split-Path -Parent $PSScriptRoot
$startupDir = [Environment]::GetFolderPath('Startup')
$shortcutFile = Join-Path $startupDir 'DexFraggler background runner.lnk'
if ($Remove) { if (Test-Path -LiteralPath $shortcutFile) { Remove-Item -LiteralPath $shortcutFile }; Write-Output 'Automatic startup disabled.'; exit }
$scriptFile = Join-Path $taskRoot 'runner\start-hidden.ps1'
$shellObject = New-Object -ComObject WScript.Shell
$shortcut = $shellObject.CreateShortcut($shortcutFile)
$shortcut.TargetPath = (Get-Command powershell.exe).Source
$shortcut.Arguments = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $scriptFile + '"'
$shortcut.WorkingDirectory = $taskRoot
$shortcut.WindowStyle = 7
$shortcut.Save()
Write-Output 'DexFraggler will resume after Windows sign-in.'
