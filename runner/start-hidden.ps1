$taskRoot = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $taskRoot '.runtime\runner.pid'
if (Test-Path -LiteralPath $pidFile) {
 $runnerPid = [int](Get-Content -LiteralPath $pidFile)
 $existing = Get-CimInstance Win32_Process -Filter "ProcessId=$runnerPid" -ErrorAction SilentlyContinue
 if ($existing -and $existing.CommandLine -like '*runner/background.mjs*') { exit }
}
$nodePath = (Get-Command node.exe).Source
$process = Start-Process -FilePath $nodePath -ArgumentList 'runner/background.mjs' -WorkingDirectory $taskRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $taskRoot '.runtime\runner.log') -RedirectStandardError (Join-Path $taskRoot '.runtime\runner-error.log') -PassThru
Set-Content -LiteralPath $pidFile -Value $process.Id
try { $process.PriorityClass = 'BelowNormal' } catch { }
