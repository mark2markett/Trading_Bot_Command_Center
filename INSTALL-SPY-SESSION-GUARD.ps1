param([string]$Repo='C:\Users\Administrator\trading_bots\command-center')
$ErrorActionPreference='Stop'
$Repo=(Resolve-Path -LiteralPath $Repo).Path
foreach($line in Get-Content -LiteralPath (Join-Path $PSScriptRoot 'SPY-SESSION-SHA256.txt')){
    if($line -notmatch '^([a-f0-9]{64})\s+([A-Za-z0-9_.-]+)$'){throw 'Invalid SPY source checksum entry.'}
    if((Get-FileHash -LiteralPath (Join-Path $PSScriptRoot $Matches[2])).Hash -ne $Matches[1]){throw 'SPY source checksum mismatch.'}
}
. (Join-Path $PSScriptRoot 'SPY-SESSION-GUARDS.ps1')
Assert-SpySessionIdle -Repo $Repo
$python=Join-Path $Repo '.venv/Scripts/python.exe'
$helper=Join-Path $PSScriptRoot 'SPY-SESSION-INSTALL.py'
$receipt=$null;$lock=$null
try {
    $lock=[IO.File]::Open((Join-Path $Repo 'var/monitor/holding-install.lock'),[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
    Assert-SpySessionIdle -Repo $Repo
    $raw=& $python -B $helper prepare --repo $Repo
    if($LASTEXITCODE -ne 0){throw 'SPY source preflight refused; no source was replaced.'}
    $plan=($raw -join "`n") | ConvertFrom-Json
    if(!$plan.ok -or !$plan.receipt){throw 'SPY source receipt missing.'}
    $receipt=$plan.receipt
    Write-Host ('SPY source recovery receipt: '+$receipt)
    Assert-SpySessionIdle -Repo $Repo
    & $python -B $helper apply --repo $Repo --receipt $receipt
    if($LASTEXITCODE -ne 0){throw 'SPY source apply needs review; preserve the receipt.'}
    & $python -B $helper verify --repo $Repo --receipt $receipt
    if($LASTEXITCODE -ne 0){throw 'SPY source readback differs; preserve the receipt.'}
} catch {
    throw ($_.Exception.Message+' Recovery receipt (if created): '+$receipt)
} finally {if($lock){$lock.Dispose()}}
Write-Host 'SPY session-date guard installed. Intraday sessions, shared SDK, server, dashboard, orders, paper state and controls were not changed. Full runtime/display repair remains deferred until all bot commands are idle.'
