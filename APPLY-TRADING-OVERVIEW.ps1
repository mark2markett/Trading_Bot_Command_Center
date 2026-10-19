param([string]$Repo='C:\Users\Administrator\trading_bots\command-center')
$ErrorActionPreference='Stop'
$Repo=(Resolve-Path -LiteralPath $Repo).Path
foreach ($line in Get-Content -LiteralPath (Join-Path $PSScriptRoot 'ACTIVITY-SHA256.txt')) {
    if ($line -notmatch '^([a-f0-9]{64})\s+([A-Za-z0-9_.-]+)$') { throw 'Invalid overview checksum entry.' }
    if ((Get-FileHash -LiteralPath (Join-Path $PSScriptRoot $Matches[2])).Hash -ne $Matches[1]) { throw 'Overview checksum mismatch.' }
}
$lock=$null
try {
    $lock=[IO.File]::Open((Join-Path $Repo 'var\monitor\holding-install.lock'),[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
    & (Join-Path $Repo '.venv\Scripts\python.exe') -B (Join-Path $PSScriptRoot 'APPLY-TRADING-OVERVIEW.py') --repo $Repo
    if ($LASTEXITCODE -ne 0) { throw 'Overview installation needs attention; preserve the printed receipt.' }
    Write-Host 'Rebuilt overview verified. Press Ctrl+F5. No server restart, task changes, trading-source changes or financial writes.'
} finally { if ($lock) { $lock.Dispose() } }
