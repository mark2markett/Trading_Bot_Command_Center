param([string]$Repo = 'C:\Users\Administrator\trading_bots\command-center')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $Repo
$Repo = (Resolve-Path -LiteralPath $Repo).Path
$python = Join-Path $Repo '.venv\Scripts\python.exe'
$tip = 'ff9a16f937d960fbc41cc21ea0ee6dfadd19b104'
$base = '54390e0f13a50c540188b04ec23efb2bbe8287e2'
$allowed = @('cc_server/cc_server/api.py', 'cc_server/tests/test_fleet_schedule.py',
    'cc_web/e2e/dashboard-wrap.spec.ts', 'cc_web/src/app/FleetPage.tsx',
    'cc_web/src/app/Stubs.tsx', 'cc_web/src/lib/api.ts', 'cc_web/src/styles/app.css')
if (!(Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Repository Python is missing.' }
$branch = git branch --show-current
if ($LASTEXITCODE -ne 0 -or $branch -ne 'feat/options-m7') {
    throw 'Expected feat/options-m7. No branch was switched.'
}
foreach ($state in @('CHERRY_PICK_HEAD', 'MERGE_HEAD', 'REBASE_HEAD')) {
    $path = git rev-parse --git-path $state
    if ($LASTEXITCODE -ne 0 -or (Test-Path -LiteralPath $path)) { throw 'Finish the existing Git operation first.' }
}
$dirty = @(git status --porcelain -- $allowed)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -ne 0) {
    throw 'A dashboard repair target has local changes. Preserve them; no running task was changed.'
}
$server = Get-ScheduledTask -TaskName 'CC server' -ErrorAction Stop
if ($server.Actions.Count -ne 1 -or $server.Actions[0].Arguments -notmatch '-m\s+cc_server\.main\b' -or
    $server.Actions[0].WorkingDirectory.TrimEnd('\') -ne $Repo.TrimEnd('\')) {
    throw 'Server task does not use the expected repository/module.'
}
foreach ($name in @('command-center-dashboard-fix.bundle', 'command-center-dashboard-dist.zip', 'DASHBOARD-RELEASE.json')) {
    $rows = @(Get-Content -LiteralPath (Join-Path $PSScriptRoot 'DASHBOARD-SHA256.txt') |
        Where-Object { $_ -match ('^[a-fA-F0-9]{64}\s+\*?' + [regex]::Escape($name) + '$') })
    if ($rows.Count -ne 1 -or (Get-FileHash -LiteralPath (Join-Path $PSScriptRoot $name) -Algorithm SHA256).Hash -ne ($rows[0] -split '\s+')[0]) {
        throw "Payload checksum mismatch: $name"
    }
}
$release = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'DASHBOARD-RELEASE.json') -Raw | ConvertFrom-Json
if ($release.source_commit -ne $tip) { throw 'Unexpected dashboard release identity.' }
$bundle = Join-Path $PSScriptRoot 'command-center-dashboard-fix.bundle'
git bundle verify $bundle
if ($LASTEXITCODE -ne 0) { throw 'Bundle verification failed; no source or task was changed.' }
git -c gc.auto=0 -c maintenance.auto=false fetch --no-auto-maintenance $bundle $tip
if ($LASTEXITCODE -ne 0) { throw 'Dashboard source import failed.' }
$parent = git rev-parse "$($tip)^"
if ($LASTEXITCODE -ne 0 -or $parent -ne $base) { throw 'Unexpected dashboard history.' }
$paths = @(git diff-tree --no-commit-id --name-only -r $tip)
if ($LASTEXITCODE -ne 0 -or $paths.Count -ne $allowed.Count -or @($paths | Where-Object { $_ -notin $allowed }).Count -ne 0) {
    throw 'Repair changed files outside the dashboard allowlist.'
}

$stage = Join-Path $env:TEMP ('cc-dashboard-stage-' + [guid]::NewGuid().ToString('N'))
$backup = Join-Path $Repo ('var\backups\dashboard-dist-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N'))
$dist = Join-Path $Repo 'cc_web\dist'
$oldCCVar = $env:CC_VAR
try {
    Expand-Archive -LiteralPath (Join-Path $PSScriptRoot 'command-center-dashboard-dist.zip') -DestinationPath $stage -ErrorAction Stop
    foreach ($asset in $release.files) {
        if ((Get-FileHash -LiteralPath (Join-Path $stage $asset.path) -Algorithm SHA256).Hash -ne $asset.sha256) {
            throw "Built asset checksum mismatch: $($asset.path)"
        }
    }
    $patch = @(git cherry HEAD $tip $base)
    if ($LASTEXITCODE -ne 0) { throw 'Could not inspect existing dashboard repair.' }
    if ($patch -match '^\+ ') {
        git -c gc.auto=0 -c maintenance.auto=false cherry-pick $tip
        if ($LASTEXITCODE -ne 0) { throw 'Cherry-pick conflict. Preserve the checkout; do not reset or switch branches.' }
    } else { Write-Host 'Dashboard source repair already present.' }

    # Only a temporary ledger is used by this regression. No live database writes.
    $env:CC_VAR = Join-Path $stage 'test-var'
    & $python -B -m pytest -q cc_server\tests\test_fleet_schedule.py --basetemp "$stage\pytest-temp" -o "cache_dir=$stage\pytest-cache"
    if ($LASTEXITCODE -ne 0) { throw 'Schedule regression failed; the running server was not stopped.' }
    Remove-Item -LiteralPath (Join-Path $stage 'test-var'), (Join-Path $stage 'pytest-temp'), (Join-Path $stage 'pytest-cache') -Recurse -Force -ErrorAction SilentlyContinue
    if ($null -eq $oldCCVar) { Remove-Item Env:\CC_VAR -ErrorAction SilentlyContinue } else { $env:CC_VAR = $oldCCVar }

    try {
        if ((Get-ScheduledTask -TaskName 'CC server').State -eq 'Running') {
            Stop-ScheduledTask -TaskName 'CC server' -ErrorAction Stop
        }
        $released = $false
        for ($i = 0; $i -lt 15; $i++) {
            if (!(Get-NetTCPConnection -LocalPort 8585 -State Listen -ErrorAction SilentlyContinue)) { $released = $true; break }
            Start-Sleep -Seconds 1
        }
        if (!$released) { throw 'Port 8585 remains occupied. No process was force-stopped.' }
        New-Item -ItemType Directory -Path (Split-Path $backup -Parent) -Force | Out-Null
        if (Test-Path -LiteralPath $dist) { Move-Item -LiteralPath $dist -Destination $backup -ErrorAction Stop }
        try { Move-Item -LiteralPath $stage -Destination $dist -ErrorAction Stop }
        catch {
            if ((Test-Path -LiteralPath $backup) -and !(Test-Path -LiteralPath $dist)) {
                Move-Item -LiteralPath $backup -Destination $dist -ErrorAction Stop
            }
            throw
        }
    }
    finally { Start-ScheduledTask -TaskName 'CC server' -ErrorAction Stop }

    $health = $null
    for ($i = 0; $i -lt 15; $i++) {
        try {
            $health = Invoke-RestMethod http://127.0.0.1:8585/api/health -TimeoutSec 3 -ErrorAction Stop
            if ($health.ok) { break }
        } catch { }
        Start-Sleep -Seconds 2
    }
    if (!$health -or !$health.ok) { throw 'Dashboard installed, but server health did not recover; retain the asset backup and inspect server.log.' }
    $fleet = Invoke-RestMethod http://127.0.0.1:8585/api/fleet -TimeoutSec 10 -ErrorAction Stop
    foreach ($run in $fleet.schedule) {
        if ($run.status -notin @('reported', 'failed', 'pending')) { throw 'Server does not expose the repaired schedule status.' }
    }
    $page = Invoke-WebRequest http://127.0.0.1:8585/ -UseBasicParsing -TimeoutSec 10 -ErrorAction Stop
    foreach ($asset in @($release.files | Where-Object { $_.path -like 'assets/*' })) {
        if (!$page.Content.Contains($asset.path)) { throw 'Server is not serving this dashboard build.' }
        Invoke-WebRequest ("http://127.0.0.1:8585/" + $asset.path) -UseBasicParsing -TimeoutSec 10 -ErrorAction Stop | Out-Null
    }
    $health | Format-List
    $fleet.schedule | Format-Table time, bot, run, status -AutoSize
    Write-Host "Dashboard repair installed. Previous assets retained at: $backup"
    Write-Host 'Refresh the dashboard with Ctrl+F5. Bot sessions, capital, P&L, controls and task settings were preserved.'
}
finally {
    if ($null -eq $oldCCVar) { Remove-Item Env:\CC_VAR -ErrorAction SilentlyContinue } else { $env:CC_VAR = $oldCCVar }
    if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue }
}
