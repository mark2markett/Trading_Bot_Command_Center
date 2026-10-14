# Exercise the real wrapper; replace only its external child-process boundary.
$ErrorActionPreference = 'Stop'
$wrapper = if ($env:CC_WRAPPER_TEST_PATH) { $env:CC_WRAPPER_TEST_PATH } else { Join-Path $PSScriptRoot 'COMPLETE-CC-OCT14-REPAIRS.ps1' }
$native = 'APPLY-OCT14-NATIVE-FIXES.ps1'
$platform = 'COMPLETE-OCT14-SIP-REPAIR.ps1'
$collector = 'COLLECT-CC-REVIEW.ps1'
function global:powershell.exe {
    $step = [IO.Path]::GetFileName($args[-1])
    $global:oct14Calls.Add($step)
    $global:LASTEXITCODE = $global:oct14Exits[$step]
}
foreach ($scenario in @(@(0,1,0), @(1,0,0), @(0,0,1), @(0,0,0))) {
    $global:oct14Calls = [Collections.Generic.List[string]]::new()
    $global:oct14Exits = @{ $native=$scenario[0]; $platform=$scenario[1]; $collector=$scenario[2] }
    $failed = $false
    try { & $wrapper } catch { $failed = $true }
    if (($oct14Calls -join ',') -ne (@($native,$platform,$collector) -join ',')) {
        throw ('Independent steps were skipped or misordered: ' + ($oct14Calls -join ','))
    }
    $expectedFailure = ($scenario | Where-Object { $_ -ne 0 }).Count -gt 0
    if ($failed -ne $expectedFailure) { throw 'Wrapper reported the wrong overall result.' }
}
Write-Host 'PASS: native, platform and collection outcomes remain independent and truthful (4 scenarios).'
