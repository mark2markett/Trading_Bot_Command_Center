param([string]$Repo='C:\Users\Administrator\trading_bots\command-center')
$ErrorActionPreference='Stop'
$Repo=(Resolve-Path -LiteralPath $Repo).Path
foreach ($line in Get-Content -LiteralPath (Join-Path $PSScriptRoot 'OPERATIONS-SHA256.txt')) {
    if ($line -notmatch '^([a-f0-9]{64})\s+([A-Za-z0-9_.-]+)$') { throw 'Invalid operations checksum entry.' }
    if ((Get-FileHash -LiteralPath (Join-Path $PSScriptRoot $Matches[2])).Hash -ne $Matches[1]) { throw 'Operations checksum mismatch.' }
}
$python=Join-Path $Repo '.venv\Scripts\python.exe'
$power=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$helper=Join-Path $PSScriptRoot 'OPERATIONS-REPAIR.py'
. (Join-Path $PSScriptRoot 'ATTENTION-TASK-OWNERSHIP.ps1')
function Get-OwnedOperationsServer {
    $task=Get-ScheduledTask -TaskName 'CC server' -TaskPath '\' -ErrorAction Stop
    if ($task.Actions.Count -ne 1 -or !$task.Settings.Enabled -or
        (Resolve-Path -LiteralPath $task.Actions[0].Execute.Trim('"')).Path -ne $python -or
        $task.Actions[0].Arguments -notmatch '^\s*(-u\s+)?-m\s+cc_server\.main\s*$' -or
        $task.Actions[0].WorkingDirectory.TrimEnd('\') -ne $Repo.TrimEnd('\')) { throw 'Server ownership differs; recovery refused.' }
    return $task
}
function Get-OwnedOperationsMonitor {
    $task=Get-ScheduledTask -TaskName 'CC health monitor' -TaskPath '\' -ErrorAction Stop
    if (!(Test-AttentionMonitorOwnership $task $Repo $power)) { throw 'Monitor ownership differs; recovery refused.' }
    return $task
}
function Test-OperationsHealth {
    try {
        $health=Invoke-RestMethod 'http://127.0.0.1:8585/api/health' -TimeoutSec 2
        return ($health.ok -and [IO.Path]::GetFullPath($health.db) -eq (Join-Path $Repo 'var\cc.db'))
    } catch { return $false }
}
$raw=& $python -B $helper prepare --repo $Repo
if ($LASTEXITCODE -ne 0) { throw 'Offline paper/options-only preflight failed; no service was restarted.' }
$prepared=($raw -join "`n") | ConvertFrom-Json
if (!$prepared.ok -or !$prepared.receipt) { throw 'Operations receipt missing.' }
$receipt=$prepared.receipt
Write-Host ('Operations recovery receipt: '+$receipt)
$lock=$null;$restoreMonitor=$false
try {
    $lock=[IO.File]::Open((Join-Path $Repo 'var\monitor\holding-install.lock'),[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
    $server=Get-OwnedOperationsServer
    $monitor=Get-OwnedOperationsMonitor
    if (!$monitor.Settings.Enabled) { throw 'Expected the enabled health monitor; its disabled state was preserved.' }
    if (!(Test-OperationsHealth)) {
        Write-Host 'Local API is unresponsive. Recovering only the verified Command Center server.'
        $restoreMonitor=$true
        Disable-ScheduledTask -TaskName 'CC health monitor' -TaskPath '\' | Out-Null
        for ($i=0;$i -lt 45;$i++) {
            if ((Get-OwnedOperationsMonitor).State -ne 'Running') { break }
            Start-Sleep -Seconds 1
        }
        if ((Get-OwnedOperationsMonitor).State -eq 'Running') { throw 'Monitor has not finished; no process was forced to stop.' }
        $server=Get-OwnedOperationsServer
        if ($server.State -eq 'Running') { Stop-ScheduledTask -TaskName 'CC server' -TaskPath '\' }
        $closed=$false
        for ($i=0;$i -lt 20;$i++) {
            if ((Get-OwnedOperationsServer).State -eq 'Ready' -and !(Get-NetTCPConnection -LocalPort 8585 -State Listen -ErrorAction SilentlyContinue)) { $closed=$true;break }
            Start-Sleep -Seconds 1
        }
        if (!$closed) { throw 'Server task or listener has not stopped; no process was forced to stop.' }
        Get-OwnedOperationsServer | Out-Null
        Start-ScheduledTask -TaskName 'CC server' -TaskPath '\'
        $healthy=$false
        for ($i=0;$i -lt 20;$i++) {
            if (Test-OperationsHealth) { $healthy=$true;break }
            Start-Sleep -Seconds 1
        }
        if (!$healthy) { throw 'Owned server recovery is not verified; no source was installed.' }
    }
} finally {
    try {
        if ($restoreMonitor) {
            Get-OwnedOperationsMonitor | Out-Null
            Enable-ScheduledTask -TaskName 'CC health monitor' -TaskPath '\' | Out-Null
        }
    } finally { if ($lock) { $lock.Dispose() } }
}
& (Join-Path $PSScriptRoot 'ENFORCE-OPTIONS-ONLY.ps1') -Repo $Repo
$monitor=Get-OwnedOperationsMonitor
if (!$monitor.Settings.Enabled) { throw ('Monitor disabled after source installation. Preserve receipt: '+$receipt) }
if ($monitor.State -eq 'Running') {
    Write-Host 'Waiting for the current monitor check to finish before starting verification.'
    for ($i=0;$i -lt 45;$i++) {
        if ((Get-OwnedOperationsMonitor).State -ne 'Running') { break }
        Start-Sleep -Seconds 1
    }
    $monitor=Get-OwnedOperationsMonitor
    if ($monitor.State -eq 'Running') { throw ('Current monitor check did not finish; preserve receipt: '+$receipt) }
}
$after=[DateTimeOffset]::UtcNow
if ($monitor.State -eq 'Ready') { Start-ScheduledTask -TaskName 'CC health monitor' -TaskPath '\' }
Write-Host 'Verifying a fresh check from the repaired monitor. Existing incidents remain visible until evidence resolves them.'
$watch=[Diagnostics.Stopwatch]::StartNew();$fresh=$false
while ($watch.Elapsed.TotalSeconds -lt 55) {
    try {
        $m=(Invoke-RestMethod 'http://127.0.0.1:8585/api/incidents?limit=1' -TimeoutSec 2).monitor
        if ($m.status -eq 'checking' -and $m.last_completed_at -and [DateTimeOffset]::Parse($m.last_completed_at) -ge $after) { $fresh=$true;break }
    } catch { }
    Start-Sleep -Seconds 1
}
if (!$fresh) { throw ('Source installed, but a fresh monitor completion is not verified. Preserve receipt: '+$receipt) }
& $python -B $helper verify --repo $Repo --receipt $receipt --after $after.ToString('o')
if ($LASTEXITCODE -ne 0) { throw ('Operations verification needs review. Preserve receipt: '+$receipt) }
Write-Host 'Local API, options-only controls and a fresh completed monitor check verified. Press Ctrl+F5. No bot tasks or orders were started by this repair.'
