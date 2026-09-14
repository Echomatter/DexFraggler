$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$executable = Join-Path $projectRoot 'desktop\DexFraggler.Tray.exe'
Start-Process -FilePath $executable -ArgumentList @('--root', ('"' + $projectRoot + '"')) -WorkingDirectory $projectRoot -WindowStyle Hidden
