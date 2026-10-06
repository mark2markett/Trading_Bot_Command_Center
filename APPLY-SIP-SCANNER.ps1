param([string]$Repo = 'C:\Users\Administrator\trading_bots\command-center')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $Repo
$Repo = (Resolve-Path -LiteralPath $Repo).Path
$python = Join-Path $Repo '.venv\Scripts\python.exe'
$fix = '9d2cbc2ed327b76c00dd7007dbc402ac7ba42380'
$base = '2f7bef397505bacc1b78c402a4cba47de2cc7b15'
if (!(Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Repository virtual-environment Python is missing.' }
if ((git branch --show-current).Trim() -ne 'feat/options-m7') { throw 'Expected feat/options-m7; no checkout was changed.' }
if (Get-CimInstance Win32_Process | Where-Object {
    $_.Name -match '^python(w)?\.exe$' -and $_.CommandLine -match 'bot\.py.*\b(session|decide|reconcile)\b'
}) { throw 'A bot command is running. Apply this source update after sessions finish.' }
$bundle = Join-Path $PSScriptRoot 'command-center-sip-scanner.bundle'
git bundle verify $bundle
if ($LASTEXITCODE -ne 0) { throw 'Bundle verification failed.' }
git -c gc.auto=0 -c maintenance.auto=false fetch --no-auto-maintenance $bundle 'feat/sip-scanner:test/sip-scanner'
if ($LASTEXITCODE -ne 0) { throw 'Branch import failed; preserve any existing branch state.' }
$baseState = @(git cherry HEAD $base "$($base)^")
if ($LASTEXITCODE -ne 0 -or $baseState -match '^\+ ') { throw 'Install the earlier pre-open repair first (native 26ea7cb or equivalent).' }
& $python -c "import sqlite3; from pathlib import Path; from datetime import datetime; src=Path('var/cc.db').resolve(); dst=src.parent/'backups'/('pre-sip-scanner-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'.db'); dst.parent.mkdir(exist_ok=True); a=sqlite3.connect(src.as_uri()+'?mode=ro',uri=True,timeout=5); b=sqlite3.connect(dst); a.backup(b); b.close(); a.close(); print(dst)"
if ($LASTEXITCODE -ne 0) { throw 'Ledger backup failed; no source patch was applied.' }
$patchState = @(git cherry HEAD $fix "$($fix)^")
if ($LASTEXITCODE -ne 0) { throw 'Could not inspect the scanner patch state.' }
if ($patchState -match '^\+ ') {
    git -c gc.auto=0 -c maintenance.auto=false cherry-pick $fix
    if ($LASTEXITCODE -ne 0) { throw 'Cherry-pick failed. Preserve state and share the error.' }
} else { Write-Host 'Scanner patch already present.' }
& $python -m pytest -q cc_sdk/tests/test_sip_snapshot.py cc_sdk/tests/test_scanner_diagnostics.py cc_sdk/tests/test_session_recovery.py cc_sdk/tests/test_intraday.py
if ($LASTEXITCODE -ne 0) { throw 'Native scanner tests failed; paste the output before enabling the scanner.' }
Write-Host 'Scanner client installed. Existing branch, unrelated files, server, and task schedules were preserved.'
Write-Host 'Deployment/configuration is still required: configure SCANNER_URL and SCANNER_SECRET in bots\sip_orb\.env.local after the platform endpoint is deployed.'
Write-Host 'No bot session was started. Portfolio capital was not changed.'
