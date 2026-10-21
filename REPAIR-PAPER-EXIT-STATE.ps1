param([string]$Repo='C:\Users\Administrator\trading_bots\command-center')
$ErrorActionPreference='Stop'
$Repo=(Resolve-Path -LiteralPath $Repo).Path
foreach($line in Get-Content -LiteralPath (Join-Path $PSScriptRoot 'PAPER-EXIT-SHA256.txt')){
    if($line -notmatch '^([a-f0-9]{64})\s+([A-Za-z0-9_.-]+)$'){throw 'Invalid paper exit checksum entry.'}
    if((Get-FileHash -LiteralPath (Join-Path $PSScriptRoot $Matches[2])).Hash -ne $Matches[1]){throw 'Paper exit checksum mismatch.'}
}
. (Join-Path $PSScriptRoot 'TRADE-REVIEW-GUARDS.ps1')
Assert-TradeReviewIdle
# Install the exact-session settlement guard and truthful pending-exit display first.
# Its financial-state verification must finish before any metadata correction.
& (Join-Path $PSScriptRoot 'INSTALL-TRADE-REVIEW.ps1') -Repo $Repo
if($LASTEXITCODE -ne 0){throw 'Source installation stopped. No paper exit metadata was changed.'}
$python=Join-Path $Repo '.venv/Scripts/python.exe'
$helper=Join-Path $PSScriptRoot 'PAPER-EXIT-STATE.py'
$receipt=Join-Path $Repo ('var/backups/paper-exit-'+[guid]::NewGuid().ToString('N')+'.json')
$lock=$null
try {
    $lock=[IO.File]::Open((Join-Path $Repo 'var/monitor/holding-install.lock'),[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
    Assert-TradeReviewIdle
    Write-Host ('Paper exit metadata recovery receipt: '+$receipt)
    & $python -B $helper prepare --repo $Repo --receipt $receipt
    if($LASTEXITCODE -ne 0){throw 'Paper stop evidence differs. No metadata correction was applied.'}
    Assert-TradeReviewIdle
    & $python -B $helper apply --repo $Repo --receipt $receipt
    if($LASTEXITCODE -ne 0){throw 'Paper metadata correction needs review; preserve its receipt.'}
    & $python -B $helper verify --repo $Repo --receipt $receipt
    if($LASTEXITCODE -ne 0){throw 'Paper metadata readback differs; preserve its receipt.'}
} catch {
    throw ($_.Exception.Message+' Recovery receipt (if created): '+$receipt)
} finally { if($lock){$lock.Dispose()} }
Write-Host 'Stale paper stop metadata reconciled. The SPY holding and pending paper exit remain unchanged. No broker command or fill was submitted. Press Ctrl+F5.'
