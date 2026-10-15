param([Parameter(Mandatory=$true)][string]$NativeRepo,
      [Parameter(Mandatory=$true)][string]$Python,
      [switch]$SimulateTestFailure)
$ErrorActionPreference = 'Stop'
$gitDefault = & git -C $NativeRepo config --get core.autocrlf
if ($LASTEXITCODE -ne 0 -or $gitDefault.Trim() -ne 'true') { throw 'Rehearsal requires effective core.autocrlf=true through a test-only Git environment override.' }
$source = Get-Content (Join-Path $PSScriptRoot 'APPLY-OCT14-NATIVE-FIXES.ps1') -Raw
$tip = 'dbea1523259e8c7cafd6579ed083eb40da0a7c28'
$layout = Join-Path ([IO.Path]::GetTempPath()) ('cc-stage-rehearsal-' + [guid]::NewGuid().ToString('N'))
$stage = Join-Path $layout 'source'
$testRoot = Join-Path $layout 'test-runtime'
$oldCCVar = $env:CC_VAR
$frozenBefore = (Get-FileHash (Join-Path $NativeRepo 'bots/spy_mr_bot/strategy.py') -Algorithm SHA256).Hash
New-Item -ItemType Directory -Path $layout | Out-Null
Push-Location $NativeRepo
try {
    if ($source.Contains('function Invoke-StagedNativeTests {')) {
        $begin = $source.IndexOf('function Invoke-StagedNativeTests {')
        $end = $source.IndexOf('function Assert-NoBotCommand', $begin)
        Invoke-Expression $source.Substring($begin, $end-$begin)
        $testPython = $Python
        if ($SimulateTestFailure) {
            function Fail-StagedPytest {
                if (!$env:CC_VAR.StartsWith($testRoot + [IO.Path]::DirectorySeparatorChar)) { throw 'Test runtime was not external.' }
                $tempIndex = [Array]::IndexOf($args, '--basetemp')
                if ($tempIndex -lt 0 -or !$args[$tempIndex+1].StartsWith($testRoot + [IO.Path]::DirectorySeparatorChar)) { throw 'Pytest scratch data was not external.' }
                $global:LASTEXITCODE = 1
            }
            $testPython = 'Fail-StagedPytest'
        }
        $expectedFailure = $false
        try { Invoke-StagedNativeTests -SourceStage $stage -TestRuntime $testRoot -Commit $tip -Python $testPython }
        catch {
            if (!$SimulateTestFailure -or $_.Exception.Message -notmatch 'Staged native regression failed') { throw }
            $expectedFailure = $true
        }
        if ($SimulateTestFailure -and !$expectedFailure) { throw 'A failing pytest command was accepted.' }
    } else {
        # Exercise the exact former staging block to prove the captured regression.
        $begin = $source.IndexOf('    New-Item -ItemType Directory -Path $stage')
        $end = $source.IndexOf('    Assert-Preflight', $begin)
        Invoke-Expression $source.Substring($begin, $end-$begin)
    }
    if ($env:CC_VAR -ne $oldCCVar) { throw 'Staging did not restore CC_VAR.' }
    $actual = (Get-FileHash (Join-Path $stage 'bots/spy_mr_bot/strategy.py') -Algorithm SHA256).Hash.ToLowerInvariant()
    $expected = (Get-Content (Join-Path $stage 'bots/spy_mr_bot/tests/strategy_sha256.json') -Raw | ConvertFrom-Json).sha256
    if ($actual -ne $expected) { throw 'Exported frozen strategy bytes differ from the original checksum.' }
    if ((Get-FileHash (Join-Path $NativeRepo 'bots/spy_mr_bot/strategy.py') -Algorithm SHA256).Hash -ne $frozenBefore) { throw 'Source strategy was changed by staging.' }
    if ($SimulateTestFailure) { Write-Host 'PASS: failing pytest remains blocking; external test paths and inherited CC_VAR preserved.' }
    else { Write-Host 'PASS: exact installer archive/full pytest staging succeeds with Windows Git defaults; source/frozen checksum and CC_VAR preserved.' }
} finally {
    Pop-Location
    if ($null -eq $oldCCVar) { Remove-Item Env:\CC_VAR -ErrorAction SilentlyContinue } else { $env:CC_VAR = $oldCCVar }
    if (Test-Path $layout) { Remove-Item -LiteralPath $layout -Recurse -Force }
}
