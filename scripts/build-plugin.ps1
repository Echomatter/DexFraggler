param(
    [ValidateSet('Debug', 'Release')]
    [string]$Configuration = 'Release',
    [switch]$WithJuce,
    [switch]$WithLv2
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$juceRoot = Join-Path $projectRoot 'plugin\third_party\JUCE'
$buildRoot = Join-Path $projectRoot 'plugin-build'

$cmake = Get-Command cmake -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -First 1
if (-not $cmake) {
    $vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
    if (Test-Path -LiteralPath $vswhere) {
        $vsRoot = & $vswhere -latest -version '[17.0,18.0)' -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
        if ($vsRoot) {
            $candidate = Join-Path $vsRoot 'Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe'
            if (Test-Path -LiteralPath $candidate) { $cmake = $candidate }
        }
    }
}
if (-not $cmake) { throw 'CMake was not found. Install CMake or the Visual Studio C++ workload.' }

if ($WithJuce -and -not (Test-Path -LiteralPath (Join-Path $juceRoot 'CMakeLists.txt'))) {
    New-Item -ItemType Directory -Force -Path (Split-Path $juceRoot -Parent) | Out-Null
    & git clone --depth 1 --branch 7.0.12 https://github.com/juce-framework/JUCE.git $juceRoot
    if ($LASTEXITCODE -ne 0) { throw 'JUCE download failed.' }
}

$args = @('-S', $projectRoot, '-B', $buildRoot,
    "-DCMAKE_BUILD_TYPE=$Configuration",
    '-DDEXFRAGGLER_BUILD_PLUGIN_TESTS=ON',
    '-DDEXFRAGGLER_BUILD_TABLE_TOOL=ON',
    "-DDEXFRAGGLER_BUILD_JUCE=$($WithJuce.IsPresent)",
    "-DDEXFRAGGLER_BUILD_LV2=$($WithLv2.IsPresent)")
if ($WithJuce) { $args += "-DJUCE_ROOT=$juceRoot" }
& $cmake @args
if ($LASTEXITCODE -ne 0) { throw 'DexFraggler configure failed.' }

& $cmake '--build' $buildRoot '--config' $Configuration '--parallel' '4'
if ($LASTEXITCODE -ne 0) { throw 'DexFraggler plugin build failed.' }

$ctest = Get-Command ctest -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -First 1
if (-not $ctest) {
    $cmakeDirectory = Split-Path $cmake -Parent
    $candidate = Join-Path $cmakeDirectory 'ctest.exe'
    if (Test-Path -LiteralPath $candidate) { $ctest = $candidate }
}
if (-not $ctest) { throw 'ctest was not found; the build completed but tests could not run.' }
& $ctest '--test-dir' $buildRoot '-C' $Configuration '--output-on-failure'
if ($LASTEXITCODE -ne 0) { throw 'DexFraggler plugin tests failed.' }
