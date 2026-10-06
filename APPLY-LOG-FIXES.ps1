param([string]$Repo = 'C:\Users\Administrator\trading_bots\command-center')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $Repo
$Repo = (Resolve-Path -LiteralPath $Repo).Path
$python = Join-Path $Repo '.venv\Scripts\python.exe'
$fix = 'd7ab90b44f6a630e704cb53c26a7412287db0ce7'
$base = '2f7bef397505bacc1b78c402a4cba47de2cc7b15'
if (!(Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Repository Python is missing.' }
if ((git branch --show-current).Trim() -ne 'feat/options-m7') { throw 'Expected feat/options-m7; no branch was switched.' }
if (Get-CimInstance Win32_Process | Where-Object {
    $_.Name -match '^python(w)?\.exe$' -and $_.CommandLine -match 'bot\.py.*\b(session|decide|reconcile)\b'
}) { throw 'A bot command is running. Install after sessions finish.' }
$bundle = Join-Path $PSScriptRoot 'command-center-log-fixes.bundle'
git bundle verify $bundle
if ($LASTEXITCODE -ne 0) { throw 'Bundle verification failed.' }
git -c gc.auto=0 -c maintenance.auto=false fetch --no-auto-maintenance $bundle 'fix/runtime-log-review-20261006:test/log-review-fixes'
if ($LASTEXITCODE -ne 0) { throw 'Fix import failed; preserve existing branch state.' }
$baseState = @(git cherry HEAD $base "$($base)^")
if ($LASTEXITCODE -ne 0 -or $baseState -match '^\+ ') { throw 'Install the earlier pre-open repair first (native 26ea7cb or equivalent).' }
& $python -B -c "import os,sqlite3; from pathlib import Path; from datetime import datetime; src=(Path(os.environ.get('CC_VAR','var'))/'cc.db').resolve(); dst=src.parent/'backups'/('pre-log-fix-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'.db'); dst.parent.mkdir(exist_ok=True); a=sqlite3.connect(src.as_uri()+'?mode=ro',uri=True,timeout=5); b=sqlite3.connect(dst); a.backup(b); b.close(); a.close(); print(dst)"
if ($LASTEXITCODE -ne 0) { throw 'Ledger backup failed; no source fix was applied.' }
$state = @(git cherry HEAD $fix "$($fix)^")
if ($LASTEXITCODE -ne 0) { throw 'Could not inspect patch state.' }
if ($state -match '^\+ ') {
    git -c gc.auto=0 -c maintenance.auto=false cherry-pick $fix
    if ($LASTEXITCODE -ne 0) { throw 'Cherry-pick failed; preserve state and paste the output.' }
} else { Write-Host 'Interruption fix already present.' }
& $python -m pytest -q cc_sdk/tests/test_session_recovery.py
if ($LASTEXITCODE -ne 0) { throw 'Native interruption tests failed; paste output before changing task settings.' }
Write-Host 'Interruption fix installed; feat/options-m7 preserved. Existing bot processes, task settings, controls and capital were not changed.'
Write-Host 'Forced process termination can bypass Python logging; collect task history to determine its cause.'
