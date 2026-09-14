param([string]$TrayPath = (Join-Path $PSScriptRoot 'DexFraggler.Tray.exe'))
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Web.Extensions
$assembly = [Reflection.Assembly]::LoadFrom([IO.Path]::GetFullPath($TrayPath))
$validator = $assembly.GetType('DexFragglerTray.TableExport').GetMethod('Validate', [Reflection.BindingFlags]'Public,Static')
$serializer = New-Object System.Web.Script.Serialization.JavaScriptSerializer
$targets = @(0..31 | ForEach-Object { @{kind='ideal-waveform-v1';weights=@(0, (1-$_/31), 0, ($_/31))} })
$fixture = @{format='dexfraggler-table';version=4;targetVersion='ideal-waveform-v1';config=@{allowDetune=$false;anchors=@(@{slot=0;shape='triangle'},@{slot=31;shape='saw'})};targets=$targets;model='fixture';metricVersion='current-metric';cells=@(@{algorithm=1;slot=0;patch=$null})} | ConvertTo-Json -Depth 20 -Compress
$cases = [ordered]@{
    validFormula = @{accept=$true; mutate={param($x)}}
    validDetune = @{accept=$true; mutate={param($x) $x.config.allowDetune=$true}}
    allFormulaShapes = @{accept=$true; mutate={param($x) $x.config.anchors=@(@{slot=0;shape='sine'},@{slot=10;shape='triangle'},@{slot=20;shape='square'},@{slot=31;shape='saw'}) | ForEach-Object { $serializer.DeserializeObject(($_ | ConvertTo-Json -Compress)) }}}
    rejectV2 = @{accept=$false; mutate={param($x) $x.version=2}}
    rejectV3 = @{accept=$false; mutate={param($x) $x.version=3}}
    rejectStringVersion = @{accept=$false; mutate={param($x) $x.version='4'}}
    rejectMissingTargetVersion = @{accept=$false; mutate={param($x) [void]$x.Remove('targetVersion')}}
    rejectWrongTargetVersion = @{accept=$false; mutate={param($x) $x.targetVersion='fourier-v1'}}
    rejectHarmonicConfig = @{accept=$false; mutate={param($x) $x.config.Add('harmonics',32)}}
    rejectStringBoolean = @{accept=$false; mutate={param($x) $x.config.allowDetune='false'}}
    rejectEmptyAnchors = @{accept=$false; mutate={param($x) $x.config.anchors=@()}}
    rejectDuplicateAnchors = @{accept=$false; mutate={param($x) $x.config.anchors[1].slot=0}}
    rejectUnsortedAnchors = @{accept=$false; mutate={param($x) $x.config.anchors[0].slot=31; $x.config.anchors[1].slot=0}}
    rejectFractionalSlot = @{accept=$false; mutate={param($x) $x.config.anchors[0].slot=0.5}}
    rejectOutsideSlot = @{accept=$false; mutate={param($x) $x.config.anchors[1].slot=32}}
    rejectCustomShape = @{accept=$false; mutate={param($x) $x.config.anchors[0].shape='custom'}}
    rejectAnchorData = @{accept=$false; mutate={param($x) $x.config.anchors[0].Add('target',@{})}}
    reject31Targets = @{accept=$false; mutate={param($x) $x.targets=$x.targets[0..30]}}
    rejectTargetKind = @{accept=$false; mutate={param($x) $x.targets[0].kind='fourier-v1'}}
    rejectTargetFourierData = @{accept=$false; mutate={param($x) $x.targets[0].Add('sin',@(1))}}
    rejectThreeWeights = @{accept=$false; mutate={param($x) $x.targets[0].weights=@(0,1,0)}}
    rejectNegativeWeight = @{accept=$false; mutate={param($x) $x.targets[0].weights=@(-1,2,0,0)}}
    rejectStringWeight = @{accept=$false; mutate={param($x) $x.targets[0].weights=@('0',1,0,0)}}
    rejectNaNWeight = @{accept=$false; mutate={param($x) $x.targets[0].weights=@([double]::NaN,1,0,0)}}
    rejectInfiniteWeight = @{accept=$false; mutate={param($x) $x.targets[0].weights=@([double]::PositiveInfinity,1,0,0)}}
    rejectZeroSum = @{accept=$false; mutate={param($x) $x.targets[0].weights=@(0,0,0,0)}}
    rejectWrongSum = @{accept=$false; mutate={param($x) $x.targets[0].weights=@(0,0.9,0,0)}}
    validEmptyCells = @{accept=$true; mutate={param($x) $x.cells=@()}}
    reject1025Cells = @{accept=$false; mutate={param($x) $x.cells=@(0..1024 | ForEach-Object { $null })}}
}
$checks = [ordered]@{}
foreach ($entry in $cases.GetEnumerator()) {
    $candidate = $serializer.DeserializeObject($fixture)
    & $entry.Value.mutate $candidate
    $accepted = $true
    try { [void]$validator.Invoke($null, [object[]]@(,$candidate)) } catch { $cause=$_.Exception; while ($cause.InnerException) { $cause=$cause.InnerException }; if ($cause -is [FormatException]) { $accepted=$false } else { throw } }
    $checks[$entry.Key] = ($accepted -eq $entry.Value.accept)
}
$passed = -not ($checks.Values -contains $false)
$report = @{passed=$passed;checks=$checks;networkRequests=0;liveProjectTouched=$false;finishedAt=[DateTime]::UtcNow.ToString('o')}
$json = $report | ConvertTo-Json -Depth 8
[IO.File]::WriteAllText((Join-Path $PSScriptRoot 'export-validation-test.json'), $json, (New-Object Text.UTF8Encoding($false)))
$json
if (-not $passed) { exit 1 }
