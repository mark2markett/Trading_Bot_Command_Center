param([string]$Repo='C:\Users\Administrator\trading_bots\command-center')
$ErrorActionPreference='Stop'
$Repo=(Resolve-Path -LiteralPath $Repo).Path
foreach($line in Get-Content -LiteralPath (Join-Path $PSScriptRoot 'CLOSED-PAPER-STOP-SHA256.txt')){
    if($line -notmatch '^([a-f0-9]{64})\s+([A-Za-z0-9_.-]+)$'){throw 'Invalid closed-paper-stop checksum entry.'}
    if((Get-FileHash -LiteralPath (Join-Path $PSScriptRoot $Matches[2])).Hash -ne $Matches[1]){throw 'Closed-paper-stop checksum mismatch.'}
}
. (Join-Path $PSScriptRoot 'SPY-SESSION-GUARDS.ps1')
Assert-SpySessionIdle -Repo $Repo
$python=Join-Path $Repo '.venv/Scripts/python.exe'
$helper=Join-Path $PSScriptRoot 'PAPER-EXIT-STATE.py'
$receipt=Join-Path $Repo ('var/backups/paper-exit-closed-'+[guid]::NewGuid().ToString('N')+'.json')
$lock=$null
try {
    $lock=[IO.File]::Open((Join-Path $Repo 'var/monitor/holding-install.lock'),[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
    Assert-SpySessionIdle -Repo $Repo
    Write-Host ('Closed paper stop recovery receipt: '+$receipt)
    & $python -B $helper prepare --closed-position --repo $Repo --receipt $receipt
    if($LASTEXITCODE -ne 0){throw 'Closed-position evidence differs; no stop metadata was changed.'}
    Assert-SpySessionIdle -Repo $Repo
    & $python -B $helper apply --repo $Repo --receipt $receipt
    if($LASTEXITCODE -ne 0){throw 'Stop metadata correction needs review; preserve the receipt.'}
    & $python -B $helper verify --repo $Repo --receipt $receipt
    if($LASTEXITCODE -ne 0){throw 'Stop metadata readback differs; preserve the receipt.'}
} catch {
    throw ($_.Exception.Message+' Recovery receipt (if created): '+$receipt)
} finally {if($lock){$lock.Dispose()}}
Write-Host 'Orphaned local paper stop retired. SPY remains flat; its recorded fills and closed P&L are unchanged. No broker command, bot run, source replacement or server restart occurred. Refresh the dashboard.'
