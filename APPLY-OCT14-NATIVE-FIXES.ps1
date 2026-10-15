param([string]$Repo = 'C:\Users\Administrator\trading_bots\command-center')
$ErrorActionPreference = 'Stop'
$Repo = (Resolve-Path -LiteralPath $Repo).Path
$python = Join-Path $Repo '.venv\Scripts\python.exe'
foreach ($name in @('command-center-oct14-native.bundle','OCT14-NATIVE-SOURCE.json','NATIVE-OCT14-PREFLIGHT.py','test_native_oct14_preflight.py')) {
    $rows = @(Get-Content -LiteralPath (Join-Path $PSScriptRoot 'OCT14-NATIVE-SHA256.txt') |
        Where-Object { $_ -match ('^[a-fA-F0-9]{64}\s+\*?' + [regex]::Escape($name) + '$') })
    if ($rows.Count -ne 1 -or (Get-FileHash -LiteralPath (Join-Path $PSScriptRoot $name) -Algorithm SHA256).Hash -ne ($rows[0] -split '\s+')[0]) { throw "Payload checksum mismatch: $name" }
}
$release = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'OCT14-NATIVE-SOURCE.json') -Raw | ConvertFrom-Json
$base = 'ff9a16f937d960fbc41cc21ea0ee6dfadd19b104'
$context = '8331fe68782fa55935bb18692fd6737bfa9781c3'
$tip = 'dbea1523259e8c7cafd6579ed083eb40da0a7c28'
if ($release.base -ne $base -or $release.context -ne $context -or $release.tip -ne $tip) { throw 'Unexpected release identity.' }
$allowed = @('README.md','cc_sdk/cc_sdk/intraday.py','cc_sdk/tests/test_daily_context_health.py',
    'cc_sdk/cc_sdk/options_runner.py','cc_sdk/tests/test_paper_account.py','cc_sdk/tests/test_options_runner.py',
    'cc_server/cc_server/api.py','cc_server/tests/test_paper_equity.py')
function Assert-NoBotCommand {
    if (Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
        $_.Name -match '^python(w)?\.exe$' -and
        ([string]::IsNullOrWhiteSpace($_.CommandLine) -or $_.CommandLine -match 'bot\.py\b')
    }) { throw 'A bot command is running or cannot be inspected; no processes were stopped. Install after commands finish.' }
    if (Get-ScheduledTask -ErrorAction Stop | Where-Object {
        $_.State -eq 'Running' -and ($_.TaskName -match '^CC bot\b' -or
            @($_.Actions | Where-Object { $_.Arguments -match 'bot\.py\b' }).Count -gt 0)
    }) { throw 'A bot task is running; install after it finishes.' }
}
function Assert-Preflight {
    param([switch]$RequireInstalled)
    Assert-NoBotCommand
    & $python -B (Join-Path $PSScriptRoot 'NATIVE-OCT14-PREFLIGHT.py') $Repo --git-only
    if ($LASTEXITCODE -ne 0) { throw 'Git preflight failed; local files were preserved.' }
    $value = & $python -B (Join-Path $PSScriptRoot 'NATIVE-OCT14-PREFLIGHT.py') $Repo
    if ($LASTEXITCODE -ne 0) { throw "Native preflight failed: $value" }
    $parsed = $value | ConvertFrom-Json
    if ($parsed.runtime_fingerprint -notmatch '^[a-f0-9]{64}$') { throw 'Runtime preservation fingerprint is missing; installation cannot be verified.' }
    if ($script:expectedRuntime -and $parsed.runtime_fingerprint -ne $script:expectedRuntime) { throw 'Orders or daily paper state changed during installation; preserve state and collect a review.' }
    $script:expectedRuntime = $parsed.runtime_fingerprint
    if ($RequireInstalled -and $parsed.source -ne 'installed') { throw 'Installed source identity was not verified.' }
    $value | Write-Host
}
Push-Location $Repo
$stage = Join-Path $env:TEMP ('cc-oct14-stage-' + [guid]::NewGuid().ToString('N'))
$oldCCVar = $env:CC_VAR
$restart = $false
$script:expectedRuntime = $null
try {
    $branch = git branch --show-current
    if ($LASTEXITCODE -ne 0 -or $branch.Trim() -ne 'feat/options-m7') { throw 'Expected feat/options-m7; no branch was switched.' }
    foreach ($state in @('CHERRY_PICK_HEAD','MERGE_HEAD','REBASE_HEAD')) {
        $path = git rev-parse --git-path $state
        if ($LASTEXITCODE -ne 0 -or (Test-Path -LiteralPath $path)) { throw 'Finish the existing Git operation first.' }
    }
    Assert-Preflight
    $server = Get-ScheduledTask -TaskName 'CC server' -ErrorAction Stop
    if ($server.Actions.Count -ne 1) { throw 'Expected exactly one CC server action; no task was changed.' }
    $serverExecute = (Resolve-Path -LiteralPath ([Environment]::ExpandEnvironmentVariables($server.Actions[0].Execute).Trim('"'))).Path
    if ($serverExecute -ne $python -or $server.Actions[0].Arguments -notmatch '^\s*(-u\s+)?-m\s+cc_server\.main\s*$' -or
        $server.Actions[0].WorkingDirectory.TrimEnd('\') -ne $Repo.TrimEnd('\') -or $server.State -ne 'Running') {
        throw 'Expected the running CC server task using this repository/module; no task was changed.'
    }
    $bundle = Join-Path $PSScriptRoot 'command-center-oct14-native.bundle'
    git bundle verify $bundle
    if ($LASTEXITCODE -ne 0) { throw 'Bundle verification failed.' }
    git -c gc.auto=0 -c maintenance.auto=false fetch --no-auto-maintenance $bundle 'fix/atomic-paper-entry-20261014:test/oct14-native'
    if ($LASTEXITCODE -ne 0) { throw 'Could not import the reviewed repair.' }
    $parent = git rev-parse "$($tip)^"
    if ($LASTEXITCODE -ne 0 -or $parent.Trim() -ne $context) { throw 'Unexpected atomic-entry history.' }
    $parent = git rev-parse "$($context)^"
    if ($LASTEXITCODE -ne 0 -or $parent.Trim() -ne $base) { throw 'Unexpected context repair history.' }
    $paths = @(git diff --name-only $base $tip)
    if ($LASTEXITCODE -ne 0 -or $paths.Count -ne $allowed.Count -or @($paths | Where-Object { $_ -notin $allowed }).Count -ne 0) { throw 'Repair exceeds its source allowlist.' }
    New-Item -ItemType Directory -Path $stage | Out-Null
    $archive = Join-Path $stage 'source.tar'
    git archive --format=tar --output=$archive $tip
    if ($LASTEXITCODE -ne 0) { throw 'Source staging failed.' }
    & tar -xf (Join-Path $stage 'source.tar') -C $stage
    if ($LASTEXITCODE -ne 0) { throw 'Source extraction failed.' }
    Push-Location $stage
    try {
        $env:CC_VAR = Join-Path $stage 'test-var'
        & $python -B -m pytest -q --basetemp "$stage\pytest-temp" -o "cache_dir=$stage\pytest-cache"
        if ($LASTEXITCODE -ne 0) { throw 'Staged native regression failed; installed source was not changed.' }
    } finally {
        Pop-Location
        if ($null -eq $oldCCVar) { Remove-Item Env:\CC_VAR -ErrorAction SilentlyContinue } else { $env:CC_VAR = $oldCCVar }
    }
    Assert-Preflight
    & $python -B -c "import os,sqlite3; from pathlib import Path; from datetime import datetime; src=(Path(os.environ.get('CC_VAR','var'))/'cc.db').resolve(); dst=src.parent/'backups'/('pre-oct14-native-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'.db'); dst.parent.mkdir(exist_ok=True); a=sqlite3.connect(src.as_uri()+'?mode=ro',uri=True,timeout=5); b=sqlite3.connect(dst); a.backup(b); b.close(); a.close(); print(dst)"
    if ($LASTEXITCODE -ne 0) { throw 'Consistent ledger backup failed; source was not changed.' }
    $restart = $true
    Stop-ScheduledTask -TaskName 'CC server' -ErrorAction Stop
    $released = $false
    for ($i = 0; $i -lt 15; $i++) {
        if (!(Get-NetTCPConnection -LocalPort 8585 -State Listen -ErrorAction SilentlyContinue)) { $released = $true; break }
        Start-Sleep -Seconds 1
    }
    if (!$released) { throw 'Port8585 remains occupied; no process was force-stopped.' }
    Assert-Preflight
    foreach ($fix in @($context,$tip)) {
        $parent = git rev-parse "$($fix)^"
        if ($LASTEXITCODE -ne 0) { throw 'Could not inspect repair history.' }
        $patch = @(git cherry HEAD $fix $parent.Trim())
        if ($LASTEXITCODE -ne 0) { throw 'Could not inspect installed patch equivalence.' }
        if ($patch -match '^\+ ') {
            git -c gc.auto=0 -c maintenance.auto=false cherry-pick $fix
            if ($LASTEXITCODE -ne 0) { throw 'Cherry-pick conflict; preserve checkout and paste output. Do not reset or switch branches.' }
        }
    }
    Assert-Preflight -RequireInstalled
    Start-ScheduledTask -TaskName 'CC server' -ErrorAction Stop
    $restart = $false
    $health = $null
    for ($i = 0; $i -lt 15; $i++) {
        try { $health = Invoke-RestMethod http://127.0.0.1:8585/api/health -TimeoutSec 3 -ErrorAction Stop; if ($health.ok) { break } } catch { }
        Start-Sleep -Seconds 2
    }
    if (!$health -or !$health.ok) { throw 'Source installed; server health did not recover. Preserve state and collect a review.' }
    & $python -B scripts\native_readiness.py --configuration-only
    if ($LASTEXITCODE -ne 0) { throw 'Source installed; configuration readiness needs attention.' }
    Write-Host 'Context recovery, atomic paper entry marks and accurate duplicate counting installed; server health/configuration verified.'
    Write-Host 'Bot commands were not started, stopped or restarted. Tasks, controls, positions, orders, capital, P&L and unrelated files were preserved.'
    Write-Host 'Verify next-opening authenticated SIP publication and native selection; this install does not certify a clean paper session.'
} finally {
    if ($restart) { Start-ScheduledTask -TaskName 'CC server' -ErrorAction Continue }
    if ($null -eq $oldCCVar) { Remove-Item Env:\CC_VAR -ErrorAction SilentlyContinue } else { $env:CC_VAR = $oldCCVar }
    Pop-Location
    if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue }
}
