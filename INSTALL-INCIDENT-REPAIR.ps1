param([string]$Repo='C:\Users\Administrator\trading_bots\command-center')
$ErrorActionPreference='Stop'
$Repo=(Resolve-Path -LiteralPath $Repo).Path
$python=Join-Path $Repo '.venv\Scripts\python.exe'
$helper=Join-Path $PSScriptRoot 'INSTALL-INCIDENT-REPAIR.py'
$power=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
. (Join-Path $PSScriptRoot 'ATTENTION-TASK-OWNERSHIP.ps1')
foreach ($line in Get-Content -LiteralPath (Join-Path $PSScriptRoot 'INCIDENT-REPAIR-SHA256.txt')) {
    if ($line -notmatch '^([a-f0-9]{64})\s+([A-Za-z0-9_.-]+)$') { throw 'Invalid incident checksum entry.' }
    if ((Get-FileHash -LiteralPath (Join-Path $PSScriptRoot $Matches[2])).Hash -ne $Matches[1]) { throw 'Incident checksum mismatch.' }
}
function Get-OwnedIncidentServer {
    $task=Get-ScheduledTask -TaskName 'CC server' -TaskPath '\' -ErrorAction Stop
    if ($task.Actions.Count -ne 1 -or !$task.Settings.Enabled -or
        (Resolve-Path -LiteralPath $task.Actions[0].Execute.Trim('"')).Path -ne $python -or
        $task.Actions[0].Arguments -notmatch '^\s*(-u\s+)?-m\s+cc_server\.main\s*$' -or
        $task.Actions[0].WorkingDirectory.TrimEnd('\') -ne $Repo.TrimEnd('\')) { throw 'Server task ownership differs; no process stopped.' }
    return $task
}
function Wait-IncidentPortClosed {
    for ($i=0;$i -lt 20;$i++) {
        if (!(Get-NetTCPConnection -LocalPort 8585 -State Listen -ErrorAction SilentlyContinue)) { return }
        Start-Sleep -Seconds 1
    }
    throw 'Server port remains occupied; no process forced to stop.'
}
function Wait-IncidentHealth {
    for ($i=0;$i -lt 20;$i++) {
        try {
            $health=Invoke-RestMethod 'http://127.0.0.1:8585/api/health' -TimeoutSec 2
            if ($health.ok -and [IO.Path]::GetFullPath($health.db) -eq (Join-Path $Repo 'var\cc.db')) { return }
        } catch { }
        Start-Sleep -Seconds 1
    }
    throw 'Updated server health could not be verified.'
}
$lock=$null; $receipt=$null; $restoreMonitor=$false; $serverStopped=$false; $applyAttempted=$false
try {
    $lock=[IO.File]::Open((Join-Path $Repo 'var\monitor\holding-install.lock'),[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
    $server=Get-OwnedIncidentServer
    if ($server.State -ne 'Running') { throw 'Expected the owned running server.' }
    $monitor=Get-ScheduledTask -TaskName 'CC health monitor' -TaskPath '\' -ErrorAction Stop
    if (!(Test-AttentionMonitorOwnership $monitor $Repo $power)) { throw 'Monitor task ownership differs.' }
    $raw=& $python -B $helper prepare --repo $Repo
    if ($LASTEXITCODE -ne 0) { throw 'Incident preflight failed; no runtime files changed.' }
    $prepared=($raw -join "`n") | ConvertFrom-Json
    if (!$prepared.ok -or !$prepared.receipt) { throw 'Preflight receipt missing.' }
    $receipt=$prepared.receipt
    Write-Host ('Recovery receipt: '+$receipt)
    $restoreMonitor=[bool]$monitor.Settings.Enabled
    Disable-ScheduledTask -TaskName 'CC health monitor' -TaskPath '\' | Out-Null
    for ($i=0;$i -lt 45;$i++) {
        if ((Get-ScheduledTask -TaskName 'CC health monitor' -TaskPath '\').State -ne 'Running') { break }
        Start-Sleep -Seconds 1
    }
    if ((Get-ScheduledTask -TaskName 'CC health monitor' -TaskPath '\').State -eq 'Running') { throw 'Monitor still running; retry after its check finishes.' }
    Get-OwnedIncidentServer | Out-Null
    $serverStopped=$true
    Stop-ScheduledTask -TaskName 'CC server' -TaskPath '\'
    Wait-IncidentPortClosed
    $applyAttempted=$true
    & $python -B $helper apply --repo $Repo --receipt $receipt
    if ($LASTEXITCODE -ne 0) { throw 'Incident update failed; source recovery was attempted.' }
    Get-OwnedIncidentServer | Out-Null
    Start-ScheduledTask -TaskName 'CC server' -TaskPath '\'
    Wait-IncidentHealth
    & $python -B $helper verify --repo $Repo --receipt $receipt
    if ($LASTEXITCODE -ne 0) { throw 'Incident endpoint or served dashboard verification failed.' }
    $serverStopped=$false
    Write-Host 'Incident monitor repair installed. Two fresh healthy minute checks can resolve recovered valuation alerts. Historical failed runs remain for review. No bot commands, orders, controls or schedules changed.'
} catch {
    $original=$_.Exception.Message
    if ($serverStopped) {
        try {
            Get-OwnedIncidentServer | Out-Null
            Stop-ScheduledTask -TaskName 'CC server' -TaskPath '\'
            Wait-IncidentPortClosed
            if ($applyAttempted) {
                & $python -B $helper rollback --repo $Repo --receipt $receipt
                if ($LASTEXITCODE -ne 0) { throw 'Automatic source rollback failed.' }
            }
            Get-OwnedIncidentServer | Out-Null
            Start-ScheduledTask -TaskName 'CC server' -TaskPath '\'
            Wait-IncidentHealth
            $serverStopped=$false
        } catch {
            if ($applyAttempted) { $restoreMonitor=$false }
            Write-Warning ('Server recovery needs attention: '+$_.Exception.Message+'; preserve the receipt. Automatic monitor restart stays disabled if source restoration is unverified.')
        }
    }
    throw ($original+' Recovery receipt: '+$receipt)
} finally {
    try {
        if ($restoreMonitor) {
            $currentMonitor=Get-ScheduledTask -TaskName 'CC health monitor' -TaskPath '\' -ErrorAction Stop
            if (!(Test-AttentionMonitorOwnership $currentMonitor $Repo $power)) { throw 'Monitor ownership changed; automatic restoration refused.' }
            Enable-ScheduledTask -TaskName 'CC health monitor' -TaskPath '\' | Out-Null
        }
    } finally { if ($lock) { $lock.Dispose() } }
}
