param([string]$Repo = 'C:\Users\Administrator\trading_bots\command-center')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $Repo
$Repo = (Resolve-Path -LiteralPath $Repo).Path
$python = Join-Path $Repo '.venv\Scripts\python.exe'
$tip = 'db9b50744fc2c10af7b18b32b939da75f8c5bd6a'
$base = '2783f2eae2657a9d60b37f4ac5053715633ed683'
if (!(Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Repository Python is missing.' }
if ((git branch --show-current).Trim() -ne 'feat/options-m7') { throw 'Expected feat/options-m7; no branch was switched.' }
if (Get-CimInstance Win32_Process | Where-Object {
    $_.Name -match '^python(w)?\.exe$' -and $_.CommandLine -match 'bot\.py.*\b(session|decide|reconcile)\b'
}) { throw 'A bot command is running. Install after it finishes; do not force-stop it.' }
$bundle = Join-Path $PSScriptRoot 'command-center-runtime-fixes.bundle'
$manifest = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'SHA256.txt')
foreach ($file in @('command-center-runtime-fixes.bundle','command-center-web.zip')) {
    $row = @($manifest | Where-Object { $_ -match ('^[a-fA-F0-9]{64}\s+\*?' + [regex]::Escape($file) + '$') })
    if ($row.Count -ne 1) { throw "Missing checksum for $file." }
    $expected = ($row[0] -split '\s+')[0]
    $actual = (Get-FileHash -LiteralPath (Join-Path $PSScriptRoot $file) -Algorithm SHA256).Hash
    if ($actual -ne $expected) { throw "Checksum mismatch: $file." }
}
git bundle verify $bundle
if ($LASTEXITCODE -ne 0) { throw 'Bundle verification failed.' }
git -c gc.auto=0 -c maintenance.auto=false fetch --no-auto-maintenance $bundle 'fix/runtime-log-review-20261006:test/runtime-readiness-fixes'
if ($LASTEXITCODE -ne 0) { throw 'Fix import failed.' }
git merge-base --is-ancestor $base HEAD
if ($LASTEXITCODE -ne 0) { throw 'Expected the feat/options-m7 base 2783f2e in this checkout.' }
& $python -B -c "import os,sqlite3; from pathlib import Path; from datetime import datetime; src=(Path(os.environ.get('CC_VAR','var'))/'cc.db').resolve(); dst=src.parent/'backups'/('pre-runtime-fix-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'.db'); dst.parent.mkdir(exist_ok=True); a=sqlite3.connect(src.as_uri()+'?mode=ro',uri=True,timeout=5); b=sqlite3.connect(dst); a.backup(b); b.close(); a.close(); print(dst)"
if ($LASTEXITCODE -ne 0) { throw 'Ledger backup failed; source was not changed.' }
$server = Get-ScheduledTask -TaskName 'CC server' -ErrorAction Stop
if ($server.State -eq 'Running') { Stop-ScheduledTask -TaskName 'CC server' }
Start-Sleep -Seconds 3
if (Get-NetTCPConnection -LocalPort 8585 -State Listen -ErrorAction SilentlyContinue) {
    throw 'An old server still owns port 8585. No process was force-stopped; paste this output.'
}
$commits = @(git rev-list --reverse "$base..$tip")
if ($LASTEXITCODE -ne 0 -or $commits.Count -eq 0) { throw 'Could not inspect update history.' }
foreach ($commit in $commits) {
    $state = @(git cherry HEAD $commit "$($commit)^")
    if ($LASTEXITCODE -ne 0) { throw 'Could not inspect an existing patch.' }
    if ($state -match '^\+ ') {
        git -c gc.auto=0 -c maintenance.auto=false cherry-pick $commit
        if ($LASTEXITCODE -ne 0) { throw 'Cherry-pick conflict; preserve state and paste output. Do not reset or switch branches.' }
    } else { Write-Host "Already present: $commit" }
}
$suiteRoot = Join-Path $env:TEMP ('cc-native-tests-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $suiteRoot | Out-Null
$originalCCVar = $env:CC_VAR
$dailyLog = Join-Path $Repo 'bots\spy_mr_bot\bot.log'
$dailyLogBackup = Join-Path $suiteRoot 'original-spy-mr.log'
$hadDailyLog = Test-Path -LiteralPath $dailyLog -PathType Leaf
if ($hadDailyLog) { Copy-Item -LiteralPath $dailyLog -Destination $dailyLogBackup }
try {
    $env:CC_VAR = Join-Path $suiteRoot 'var'
    & $python -m pytest -q
    $suiteExit = $LASTEXITCODE
}
finally {
    if ($null -eq $originalCCVar) { Remove-Item Env:\CC_VAR -ErrorAction SilentlyContinue }
    else { $env:CC_VAR = $originalCCVar }
    if ($hadDailyLog) { Copy-Item -LiteralPath $dailyLogBackup -Destination $dailyLog -Force }
    elseif (Test-Path -LiteralPath $dailyLog) { Remove-Item -LiteralPath $dailyLog }
}
if ($suiteExit -ne 0) { throw 'Native tests failed; server remains stopped. Paste the output before starting sessions.' }
$webStage = Join-Path $env:TEMP ('cc-web-build-' + [guid]::NewGuid().ToString('N'))
Expand-Archive -LiteralPath (Join-Path $PSScriptRoot 'command-center-web.zip') -DestinationPath $webStage
$dist = Join-Path $Repo 'cc_web\dist'
New-Item -ItemType Directory -Path $dist -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $webStage 'assets') -Destination $dist -Recurse -Force
Copy-Item -LiteralPath (Join-Path $webStage 'index.html') -Destination $dist -Force
Remove-Item -LiteralPath $webStage -Recurse -Force
& $python -B scripts\configure_paper_account.py --capital 100000
if ($LASTEXITCODE -ne 0) { throw 'Paper-account initialization failed; no capital reset was attempted. Paste the output.' }
Start-ScheduledTask -TaskName 'CC server' -ErrorAction Stop
Start-Sleep -Seconds 5
Invoke-RestMethod http://127.0.0.1:8585/api/health -TimeoutSec 10 -ErrorAction Stop | Format-List
Invoke-RestMethod http://127.0.0.1:8585/api/readiness -TimeoutSec 10 -ErrorAction Stop | ConvertTo-Json -Depth 8
Write-Host 'SOURCE UPDATE INSTALLED. One shared $100,000 paper account; existing P&L retained.'
Write-Host 'feat/options-m7 and unrelated files preserved. No bot sessions were started and no kill/pause flags were cleared.'
& $python -B scripts\native_readiness.py --configuration-only
if ($LASTEXITCODE -ne 0) {
    Write-Warning 'Update installed, but deployment is NOT ready. Resolve the failed prerequisites; scanner setup is documented in RUNTIME-FIXES.md.'
} else {
    Write-Host 'Configuration checks passed. Verify live readiness at 09:35-09:39 Eastern; this is not a live-data certification.'
}
