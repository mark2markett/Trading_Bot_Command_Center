$ErrorActionPreference = 'Stop'
# Mark's invocation acknowledges the linked current-head PR review.
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'COMPLETE-OCT14-SIP-REPAIR.ps1')
if ($LASTEXITCODE -ne 0) { throw 'Platform owner release needs attention; required checks were not bypassed.' }
$nativeExit = 1
try {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'APPLY-OCT14-NATIVE-FIXES.ps1')
    $nativeExit = $LASTEXITCODE
} finally {
    Write-Host 'Collecting a read-only review of the resulting state.'
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'COLLECT-CC-REVIEW.ps1')
    if ($LASTEXITCODE -ne 0) { Write-Warning 'Review collection also needs attention; retain all output.' }
}
if ($nativeExit -ne 0) { throw 'Native install needs attention; preserve the checkout and upload the collected review ZIP.' }
Write-Host 'Platform deployment and native configuration verified. End-of-day closure and next-opening SIP publication/selection still require review evidence.'
