param([string]$OutputDirectory = $PSScriptRoot)
$ErrorActionPreference = 'Stop'
$compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path -LiteralPath $compiler)) { $compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework\v4.0.30319\csc.exe' }
if (-not (Test-Path -LiteralPath $compiler)) { throw '.NET Framework C# compiler was not found.' }
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$source = Join-Path $PSScriptRoot 'Tray.cs'
$executable = Join-Path $OutputDirectory 'DexFraggler.Tray.exe'
$icon = Join-Path $OutputDirectory 'DexFraggler.ico'
$references = @('/r:System.dll','/r:System.Core.dll','/r:System.Drawing.dll','/r:System.Windows.Forms.dll','/r:System.Management.dll','/r:System.Web.Extensions.dll','/r:System.Net.Http.dll')
& $compiler /nologo /target:winexe /optimize+ /platform:anycpu @references "/out:$executable" $source
if ($LASTEXITCODE -ne 0) { throw 'Tray compilation failed.' }
$iconProcess = Start-Process -FilePath $executable -ArgumentList '--write-icon', ('"' + $icon + '"') -PassThru -Wait -WindowStyle Hidden
if ($iconProcess.ExitCode -ne 0) { throw 'Icon creation failed.' }
& $compiler /nologo /target:winexe /optimize+ /platform:anycpu @references "/win32icon:$icon" "/out:$executable" $source
if ($LASTEXITCODE -ne 0) { throw 'Tray icon compilation failed.' }
$report = Join-Path $OutputDirectory 'self-test.json'
$testProcess = Start-Process -FilePath $executable -ArgumentList '--self-test', '--report', ('"' + $report + '"') -PassThru -Wait -WindowStyle Hidden
Get-Content -LiteralPath $report
if ($testProcess.ExitCode -ne 0) { throw 'Tray self-test failed.' }
Write-Output "Built $executable"
