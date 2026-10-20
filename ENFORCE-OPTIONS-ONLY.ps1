param([string]$Repo='C:\Users\Administrator\trading_bots\command-center')
$ErrorActionPreference='Stop'
$Repo=(Resolve-Path -LiteralPath $Repo).Path
foreach ($line in Get-Content -LiteralPath (Join-Path $PSScriptRoot 'OPTIONS-ONLY-SHA256.txt')) {
    if ($line -notmatch '^([a-f0-9]{64})\s+([A-Za-z0-9_.-]+)$') { throw 'Invalid options-only checksum entry.' }
    if ((Get-FileHash -LiteralPath (Join-Path $PSScriptRoot $Matches[2])).Hash -ne $Matches[1]) { throw 'Options-only checksum mismatch.' }
}
$python=Join-Path $Repo '.venv\Scripts\python.exe'
$helper=Join-Path $PSScriptRoot 'OPTIONS-ONLY.py'
$receipt=Join-Path $Repo ('var\backups\options-only-'+[guid]::NewGuid().ToString('N')+'.json')
Write-Host ('Policy recovery receipt: '+$receipt)
try {
    & $python -B $helper contain --repo $Repo --receipt $receipt
    if ($LASTEXITCODE -ne 0) { throw 'Share entry containment failed.' }
    & (Join-Path $PSScriptRoot 'INSTALL-ACTIVITY-DASHBOARD.ps1') -Repo $Repo
    & $python -B $helper activate --repo $Repo --receipt $receipt
    if ($LASTEXITCODE -ne 0) { throw 'Options-only policy activation failed.' }
    & $python -B $helper verify --repo $Repo --receipt $receipt
    if ($LASTEXITCODE -ne 0) { throw 'Options-only verification failed.' }
    Write-Host 'Options-only entries enforced. Four share strategies paused. Existing shares and exit handling retained. Options bot controls preserved. Press Ctrl+F5.'
} catch {
    throw ($_.Exception.Message+' Restrictive pauses remain; no holdings were closed or converted. Preserve receipt: '+$receipt)
}
