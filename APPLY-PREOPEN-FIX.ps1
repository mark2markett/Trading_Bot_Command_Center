param([string]$Repo = 'C:\Users\Administrator\trading_bots\command-center')
$ErrorActionPreference = 'Stop'
$fix = '2f7bef397505bacc1b78c402a4cba47de2cc7b15'
Set-Location $Repo
$Repo = (Resolve-Path $Repo).Path
$python = Join-Path $Repo '.venv\Scripts\python.exe'
if (!(Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Repository virtual-environment Python is missing.' }
if ((git branch --show-current).Trim() -ne 'feat/options-m7') { throw 'Expected feat/options-m7.' }
if (Get-CimInstance Win32_Process | Where-Object {
    $_.Name -match '^python(w)?\.exe$' -and $_.CommandLine -match 'bot\.py.*\b(session|decide|reconcile)\b'
}) { throw 'A bot command is still running. Apply after the sessions have finished.' }
$task = Get-ScheduledTask -TaskName 'CC server'
$actions = @($task.Actions)
if ($actions.Count -ne 1 -or $actions[0].Arguments -notmatch 'cc_server\.main' -or
    $actions[0].WorkingDirectory.TrimEnd('\') -ne $Repo.TrimEnd('\') -or
    $actions[0].Execute -ne $python) {
    throw 'CC server action does not match this repository. No process was stopped.'
}
$bundle = Join-Path $PSScriptRoot 'command-center-closed-loop.bundle'
git bundle verify $bundle
if ($LASTEXITCODE -ne 0) { throw 'Bundle verification failed.' }
git -c gc.auto=0 -c maintenance.auto=false fetch --no-auto-maintenance $bundle 'test/closed-loop:test/closed-loop'
if ($LASTEXITCODE -ne 0) { throw 'Bundle import failed.' }
git cat-file -e "$($fix)^{commit}"
if ($LASTEXITCODE -ne 0) { throw 'Expected fix is missing.' }

$owners = @(Get-NetTCPConnection -LocalPort 8585 -State Listen -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique)
$identities = @{}
foreach ($owner in $owners) {
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$owner"
    if (!$process -or $process.CommandLine -notmatch 'cc_server\.main') {
        throw "Unexpected listener on 8585 ($owner). No process was stopped."
    }
    # Windows venv Python can launch a child using the base interpreter. Establish
    # the repository through that child's still-running venv parent before stopping it.
    $ancestor = $process
    $seen = @{}
    $matchesRepo = $false
    for ($depth = 0; $depth -lt 8 -and $ancestor; $depth++) {
        if ($seen.ContainsKey([int]$ancestor.ProcessId)) { break }
        $seen[[int]$ancestor.ProcessId] = $true
        if ($ancestor.ExecutablePath -eq $python -and $ancestor.CommandLine -match 'cc_server\.main') {
            $matchesRepo = $true
            break
        }
        if (!$ancestor.ParentProcessId) { break }
        $parent = Get-CimInstance Win32_Process -Filter "ProcessId=$($ancestor.ParentProcessId)"
        if (!$parent -or $parent.CreationDate -gt $ancestor.CreationDate) { break }
        $ancestor = $parent
    }
    if (!$matchesRepo -or !$process.CreationDate -or !$process.ExecutablePath) {
        throw "Listener $owner could not be verified against this repository's Python. No process was stopped."
    }
    $identities[$owner] = $process
}
Export-ScheduledTask -TaskName 'CC server' | Set-Content (Join-Path $PSScriptRoot 'CC-server-before.xml') -Encoding Unicode
if ($task.State -eq 'Running') { Stop-ScheduledTask -TaskName 'CC server' }
Start-Sleep -Seconds 2
foreach ($owner in $owners) {
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$owner"
    if ($process) {
        $original = $identities[$owner]
        if ($process.CreationDate -ne $original.CreationDate -or
            $process.ExecutablePath -ne $original.ExecutablePath -or
            $process.CommandLine -ne $original.CommandLine) {
            throw 'Listener process identity changed. No replacement process was stopped.'
        }
        Stop-Process -Id $owner -Force
    }
}
if (Get-NetTCPConnection -LocalPort 8585 -State Listen -ErrorAction SilentlyContinue) { throw 'Port 8585 remains occupied.' }

& $python -c "import sqlite3; from pathlib import Path; from datetime import datetime; src=Path('var/cc.db').resolve(); dst=src.parent/'backups'/('pre-preopen-fix-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'.db'); dst.parent.mkdir(exist_ok=True); a=sqlite3.connect(src.as_uri()+'?mode=ro',uri=True,timeout=5); b=sqlite3.connect(dst); a.backup(b); b.close(); a.close(); print(dst)"
if ($LASTEXITCODE -ne 0) { throw 'Ledger snapshot failed; server remains stopped.' }
$patchState = @(git cherry HEAD $fix "$($fix)^")
if ($LASTEXITCODE -ne 0) { throw 'Could not inspect patch state.' }
if ($patchState -match '^\+ ') {
    git -c gc.auto=0 -c maintenance.auto=false cherry-pick $fix
    if ($LASTEXITCODE -ne 0) { throw 'Cherry-pick failed. Preserve the state and paste the error.' }
} else {
    Write-Host 'Fix is already present.'
}

$settings = (Get-ScheduledTask -TaskName 'CC server').Settings
Write-Host "Previous server execution limit: $($settings.ExecutionTimeLimit)"
$settings.ExecutionTimeLimit = 'PT0S'
Set-ScheduledTask -TaskName 'CC server' -Settings $settings | Out-Null
Start-ScheduledTask -TaskName 'CC server'
Start-Sleep -Seconds 5
Invoke-RestMethod 'http://127.0.0.1:8585/api/health' -TimeoutSec 10 | Format-List
& $python (Join-Path $PSScriptRoot 'PREOPEN-CHECK.py') $Repo
if ($LASTEXITCODE -ne 0) { throw 'A pre-open prerequisite needs attention; paste the output.' }
Get-ScheduledTask -TaskName 'CC bot *' | ForEach-Object {
    $info = $_ | Get-ScheduledTaskInfo
    Write-Host "$($_.TaskName): $($_.State), next=$($info.NextRunTime)"
}
Write-Host 'Source installed; server restarted. Bot schedules were preserved. No sessions were started.'
