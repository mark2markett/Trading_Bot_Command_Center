param([string]$Repo = 'C:\Users\Administrator\trading_bots\command-center')
$ErrorActionPreference = 'Stop'
$Repo = (Resolve-Path -LiteralPath $Repo).Path
$python = Join-Path $Repo '.venv\Scripts\python.exe'
$fix = '8331fe68782fa55935bb18692fd6737bfa9781c3'
$base = 'ff9a16f937d960fbc41cc21ea0ee6dfadd19b104'
$allowed = @('README.md','cc_sdk/cc_sdk/intraday.py','cc_sdk/tests/test_daily_context_health.py')
if (!(Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Repository Python is missing.' }
foreach ($name in @('command-center-context-health.bundle','NATIVE-CONTEXT-PREFLIGHT.py','test_native_context_preflight.py')) {
    $rows = @(Get-Content -LiteralPath (Join-Path $PSScriptRoot 'CONTEXT-HEALTH-SHA256.txt') |
        Where-Object { $_ -match ('^[a-fA-F0-9]{64}\s+\*?' + [regex]::Escape($name) + '$') })
    if ($rows.Count -ne 1 -or (Get-FileHash -LiteralPath (Join-Path $PSScriptRoot $name) -Algorithm SHA256).Hash -ne ($rows[0] -split '\s+')[0]) {
        throw "Payload checksum mismatch: $name"
    }
}
function Assert-NoBotCommand {
    if (Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
        $_.Name -match '^python(w)?\.exe$' -and
        ([string]::IsNullOrWhiteSpace($_.CommandLine) -or $_.CommandLine -match 'bot\.py.*\b(session|decide|reconcile)\b')
    }) { throw 'A bot command is running or a Python process cannot be inspected. Install after commands finish; no processes were stopped.' }
    if (Get-ScheduledTask -ErrorAction Stop | Where-Object {
        $_.State -eq 'Running' -and @($_.Actions | Where-Object { $_.Arguments -match 'bot\.py.*\b(session|decide|reconcile)\b' }).Count -gt 0
    }) { throw 'A bot task is running; install after it finishes.' }
}
Push-Location $Repo
$stage = Join-Path $env:TEMP ('cc-context-stage-' + [guid]::NewGuid().ToString('N'))
$oldCCVar = $env:CC_VAR
try {
    $branch = git branch --show-current
    if ($LASTEXITCODE -ne 0 -or $branch.Trim() -ne 'feat/options-m7') { throw 'Expected feat/options-m7; no branch was switched.' }
    foreach ($state in @('CHERRY_PICK_HEAD','MERGE_HEAD','REBASE_HEAD')) {
        $path = git rev-parse --git-path $state
        if ($LASTEXITCODE -ne 0 -or (Test-Path -LiteralPath $path)) { throw 'Finish the existing Git operation first.' }
    }
    $dirty = @(git status --porcelain)
    if ($LASTEXITCODE -ne 0 -or $dirty.Count -ne 0) { throw 'Checkout has local changes; preserve them before applying the repair.' }
    Assert-NoBotCommand
    & $python -B (Join-Path $PSScriptRoot 'NATIVE-CONTEXT-PREFLIGHT.py') $Repo
    if ($LASTEXITCODE -ne 0) { throw 'Native preflight failed; no source was changed.' }
    $bundle = Join-Path $PSScriptRoot 'command-center-context-health.bundle'
    git bundle verify $bundle
    if ($LASTEXITCODE -ne 0) { throw 'Bundle verification failed; install the earlier dashboard source first.' }
    git -c gc.auto=0 -c maintenance.auto=false fetch --no-auto-maintenance $bundle 'fix/daily-context-health-20261013:test/daily-context-health'
    if ($LASTEXITCODE -ne 0) { throw 'Repair import failed.' }
    $parent = git rev-parse "$($fix)^"
    if ($LASTEXITCODE -ne 0 -or $parent.Trim() -ne $base) { throw 'Unexpected native repair history.' }
    $paths = @(git diff-tree --no-commit-id --name-only -r $fix)
    if ($LASTEXITCODE -ne 0 -or $paths.Count -ne $allowed.Count -or @($paths | Where-Object { $_ -notin $allowed }).Count -ne 0) { throw 'Repair exceeds its source allowlist.' }
    New-Item -ItemType Directory -Path $stage | Out-Null
    $archive = Join-Path $stage 'source.tar'
    git archive --format=tar --output=$archive $fix
    if ($LASTEXITCODE -ne 0) { throw 'Could not stage the reviewed source.' }
    & tar -xf $archive -C $stage
    if ($LASTEXITCODE -ne 0) { throw 'Source extraction failed.' }
    Push-Location $stage
    try {
        $env:CC_VAR = Join-Path $stage 'test-var'
        & $python -B -m pytest -q cc_sdk/tests/test_daily_context_health.py cc_sdk/tests/test_session_recovery.py cc_sdk/tests/test_intraday.py cc_sdk/tests/test_options_runner.py cc_sdk/tests/test_sip_snapshot.py --basetemp "$stage\pytest-temp" -o "cache_dir=$stage\pytest-cache"
        if ($LASTEXITCODE -ne 0) { throw 'Staged regression failed; installed source is unchanged.' }
    } finally {
        Pop-Location
        if ($null -eq $oldCCVar) { Remove-Item Env:\CC_VAR -ErrorAction SilentlyContinue } else { $env:CC_VAR = $oldCCVar }
    }
    Assert-NoBotCommand
    & $python -B (Join-Path $PSScriptRoot 'NATIVE-CONTEXT-PREFLIGHT.py') $Repo
    if ($LASTEXITCODE -ne 0) { throw 'Native state changed; no source was applied.' }
    & $python -B -c "import os,sqlite3; from pathlib import Path; from datetime import datetime; src=(Path(os.environ.get('CC_VAR','var'))/'cc.db').resolve(); dst=src.parent/'backups'/('pre-context-health-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'.db'); dst.parent.mkdir(exist_ok=True); a=sqlite3.connect(src.as_uri()+'?mode=ro',uri=True,timeout=5); b=sqlite3.connect(dst); a.backup(b); b.close(); a.close(); print(dst)"
    if ($LASTEXITCODE -ne 0) { throw 'Ledger backup failed; source was not changed.' }
    $patch = @(git cherry HEAD $fix $base)
    if ($LASTEXITCODE -ne 0) { throw 'Could not inspect repair state.' }
    if ($patch -match '^\+ ') {
        git -c gc.auto=0 -c maintenance.auto=false cherry-pick $fix
        if ($LASTEXITCODE -ne 0) { throw 'Cherry-pick conflict; preserve checkout and paste output. Do not reset or switch branches.' }
    } else { Write-Host 'Native context-health repair is already installed.' }
    $result = & $python -B (Join-Path $PSScriptRoot 'NATIVE-CONTEXT-PREFLIGHT.py') $Repo
    if ($LASTEXITCODE -ne 0 -or ($result | ConvertFrom-Json).source -ne 'installed') { throw 'Installed source identity was not verified.' }
    Write-Host 'Native daily-context health repair installed and source verified. It takes effect in the next scheduled bot commands.'
    Write-Host 'No sessions were started, stopped or restarted. Tasks, controls, orders, positions, account capital and P&L were preserved.'
} finally {
    if ($null -eq $oldCCVar) { Remove-Item Env:\CC_VAR -ErrorAction SilentlyContinue } else { $env:CC_VAR = $oldCCVar }
    Pop-Location
    if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue }
}
