param([string]$Repo = 'C:\Users\Administrator\trading_bots\command-center')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $Repo
$Repo = (Resolve-Path -LiteralPath $Repo).Path
$python = Join-Path $Repo '.venv\Scripts\python.exe'
$tip = '54390e0f13a50c540188b04ec23efb2bbe8287e2'
$base = 'db9b50744fc2c10af7b18b32b939da75f8c5bd6a'
$allowed = @('cc_server/cc_server/main.py', 'cc_server/tests/test_server_startup_imports.py')
if (!(Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Repository Python is missing.' }
$branch = git branch --show-current
if ($LASTEXITCODE -ne 0 -or $branch -ne 'feat/options-m7') {
    throw 'Expected feat/options-m7. No branch was switched.'
}
$inProgress = git rev-parse --git-path CHERRY_PICK_HEAD
if ($LASTEXITCODE -ne 0 -or (Test-Path -LiteralPath $inProgress)) {
    throw 'Finish any existing cherry-pick before this repair.'
}
$dirty = @(git status --porcelain -- $allowed)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -ne 0) {
    throw 'A repair target has local changes. Preserve them and paste the output.'
}
$server = Get-ScheduledTask -TaskName 'CC server' -ErrorAction Stop
if ($server.Actions.Count -ne 1 -or $server.Actions[0].Arguments -notmatch '-m\s+cc_server\.main\b' -or
    $server.Actions[0].WorkingDirectory.TrimEnd('\') -ne $Repo.TrimEnd('\')) {
    throw 'Server task does not use the expected repository/module. Paste its action settings without secrets.'
}
$bundle = Join-Path $PSScriptRoot 'command-center-server-import-fix.bundle'
$rows = @(Get-Content -LiteralPath (Join-Path $PSScriptRoot 'SHA256.txt') |
    Where-Object { $_ -match '^[a-fA-F0-9]{64}\s+\*?command-center-server-import-fix\.bundle$' })
if ($rows.Count -ne 1) { throw 'Bundle checksum entry is missing.' }
if ((Get-FileHash -LiteralPath $bundle -Algorithm SHA256).Hash -ne ($rows[0] -split '\s+')[0]) {
    throw 'Bundle checksum mismatch.'
}
git bundle verify $bundle
if ($LASTEXITCODE -ne 0) { throw 'Bundle verification failed. No source or running task was changed.' }
git -c gc.auto=0 -c maintenance.auto=false fetch --no-auto-maintenance $bundle $tip
if ($LASTEXITCODE -ne 0) { throw 'Repair import failed.' }
$parent = git rev-parse "$($tip)^"
if ($LASTEXITCODE -ne 0 -or $parent -ne $base) { throw 'Unexpected repair history.' }
$paths = @(git diff-tree --no-commit-id --name-only -r $tip)
if ($LASTEXITCODE -ne 0 -or $paths.Count -ne $allowed.Count -or
    @($paths | Where-Object { $_ -notin $allowed }).Count -ne 0) {
    throw 'Repair changed files outside the server-only allowlist.'
}
if (!(Test-Path -LiteralPath (Join-Path $Repo 'cc_sdk\cc_sdk\paper_account.py') -PathType Leaf)) {
    throw 'The previously installed shared paper-account runtime is required.'
}
$patch = @(git cherry HEAD $tip $base)
if ($LASTEXITCODE -ne 0) { throw 'Could not inspect existing repair.' }
if ($patch -match '^\+ ') {
    git -c gc.auto=0 -c maintenance.auto=false cherry-pick $tip
    if ($LASTEXITCODE -ne 0) {
        throw 'Cherry-pick conflict. Preserve the checkout and paste output; do not reset or switch branches.'
    }
} else { Write-Host 'Server import repair already present.' }

# This test runs only a fake quote against a temporary ledger. Active bots and
# their live ledger are untouched; do not run the full native suite mid-session.
$sandbox = Join-Path $env:TEMP ('cc-server-import-test-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $sandbox | Out-Null
$oldCCVar = $env:CC_VAR
try {
    $env:CC_VAR = $sandbox
    & $python -B -m pytest -q cc_server\tests\test_server_startup_imports.py --basetemp "$sandbox\pytest-temp" -o "cache_dir=$sandbox\pytest-cache"
    if ($LASTEXITCODE -ne 0) { throw 'Startup regression failed; the running server was not stopped.' }
}
finally {
    if ($null -eq $oldCCVar) { Remove-Item Env:\CC_VAR -ErrorAction SilentlyContinue }
    else { $env:CC_VAR = $oldCCVar }
    Remove-Item -LiteralPath $sandbox -Recurse -Force -ErrorAction SilentlyContinue
}

# Restart ONLY the server. In particular, NR7 may hold an open paper position.
# Do not stop bot sessions, initialize capital, or change kill/pause controls.
try {
    if ((Get-ScheduledTask -TaskName 'CC server').State -eq 'Running') {
        Stop-ScheduledTask -TaskName 'CC server' -ErrorAction Stop
    }
    $released = $false
    for ($i = 0; $i -lt 15; $i++) {
        if (!(Get-NetTCPConnection -LocalPort 8585 -State Listen -ErrorAction SilentlyContinue)) {
            $released = $true
            break
        }
        Start-Sleep -Seconds 1
    }
    if (!$released) { throw 'Port 8585 remains occupied. No process was force-stopped; paste output.' }
}
finally {
    Start-ScheduledTask -TaskName 'CC server' -ErrorAction Stop
}

$health = $null
$lastConnectionError = ''
for ($i = 0; $i -lt 15; $i++) {
    try {
        $health = Invoke-RestMethod http://127.0.0.1:8585/api/health -TimeoutSec 3 -ErrorAction Stop
        if ($health.ok) { break }
    }
    catch { $lastConnectionError = $_.Exception.Message }
    Start-Sleep -Seconds 2
}
if (!$health -or !$health.ok) { throw "Server health did not recover: $lastConnectionError" }
$health | Format-List
$readiness = $null
for ($i = 0; $i -lt 10; $i++) {
    $readiness = Invoke-RestMethod http://127.0.0.1:8585/api/readiness -TimeoutSec 10 -ErrorAction Stop
    if ($readiness.paper_account.ready) { break }
    Start-Sleep -Seconds 3
}
$readiness | ConvertTo-Json -Depth 8
$bots = Invoke-RestMethod http://127.0.0.1:8585/api/bots -TimeoutSec 10 -ErrorAction Stop
foreach ($bot in $bots) {
    Write-Host "$($bot.id): $($bot.status) | heartbeat=$($bot.heartbeat.at) | OK=$($bot.heartbeat.ok)"
}
if (!$readiness.paper_account.ready) {
    Get-Content -LiteralPath (Join-Path $Repo 'var\logs\server.log') -Tail 20 -ErrorAction SilentlyContinue
    throw 'Import repair installed, but real paper valuation is still unavailable. Paste this output.'
}
Write-Host 'Server import repair installed; live paper valuation is ready. Bot sessions were not restarted.'
Write-Host 'SIP ORB scanner deployment/configuration remains a separate prerequisite.'
