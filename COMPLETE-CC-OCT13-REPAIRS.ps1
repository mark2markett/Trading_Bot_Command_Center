param([string]$Repo = 'C:\Users\Administrator\trading_bots\command-center')
$ErrorActionPreference = 'Stop'
# Native source installation is independent of platform release and does not restart bots.
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'APPLY-CONTEXT-HEALTH-FIX.ps1') -Repo $Repo
if ($LASTEXITCODE -ne 0) { throw 'Native context repair needs attention; preserve output and existing state.' }
# Mark remains the owner merger; the helper enforces required current-head checks.
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'COMPLETE-SIP-HEALTH-VERIFICATION.ps1')
if ($LASTEXITCODE -ne 0) { throw 'Native source installation completed; platform release/health still needs attention. Preserve the output; rerun is idempotent.' }
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'COLLECT-CC-REVIEW.ps1') -Repo $Repo
if ($LASTEXITCODE -ne 0) { throw 'Repairs installed/released, but fresh native review collection failed.' }
Write-Host 'Upload the fresh review ZIP printed above. Next-opening publication and native consumption still need verification.'
