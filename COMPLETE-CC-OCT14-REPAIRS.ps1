$ErrorActionPreference = 'Stop'
# Independent native installation must not be blocked by a moving platform base.
# Mark's invocation acknowledges the linked current-head PR review.
$nativeExit = 1
$platformExit = 1
$collectionExit = 1
try {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'APPLY-OCT14-NATIVE-FIXES.ps1')
    $nativeExit = $LASTEXITCODE
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'COMPLETE-OCT14-SIP-REPAIR.ps1')
    $platformExit = $LASTEXITCODE
} finally {
    Write-Host 'Collecting a read-only review of the resulting state.'
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'COLLECT-CC-REVIEW.ps1')
    $collectionExit = $LASTEXITCODE
}
Write-Host "Native installation exit: $nativeExit; platform release exit: $platformExit; collection exit: $collectionExit"
if ($nativeExit -ne 0 -or $platformExit -ne 0 -or $collectionExit -ne 0) {
    throw 'Some repair steps remain unverified. Preserve all output and upload the collected review ZIP; no requirement was bypassed.'
}
Write-Host 'Platform deployment and native configuration verified. End-of-day closure and next-opening SIP publication/selection still require review evidence.'
