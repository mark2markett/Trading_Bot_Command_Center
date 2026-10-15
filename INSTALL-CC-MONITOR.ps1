param([string]$Repo='C:\Users\Administrator\trading_bots\command-center',[switch]$Observation)
$ErrorActionPreference='Stop'
$Repo=(Resolve-Path -LiteralPath $Repo).Path
$root=Join-Path $Repo 'var\monitor'
$server=Get-ScheduledTask -TaskName 'CC server' -ErrorAction Stop
$python=Join-Path $Repo '.venv\Scripts\python.exe'
if ($server.Actions.Count -ne 1 -or
    (Resolve-Path -LiteralPath $server.Actions[0].Execute.Trim('"')).Path -ne $python -or
    $server.Actions[0].Arguments -notmatch '^\s*(-u\s+)?-m\s+cc_server\.main\s*$' -or
    $server.Actions[0].WorkingDirectory.TrimEnd('\') -ne $Repo.TrimEnd('\')) { throw 'Unexpected server task ownership.' }
foreach ($name in @('CC-MONITOR.py','CC-MONITOR.ps1')) {
    $rows=@(Get-Content -LiteralPath (Join-Path $PSScriptRoot 'ATTENTION-SHA256.txt') |
        Where-Object { $_ -match ('^[a-f0-9]{64}\s+'+[regex]::Escape($name)+'$') })
    if ($rows.Count -ne 1 -or (Get-FileHash -LiteralPath (Join-Path $PSScriptRoot $name)).Hash -ne ($rows[0] -split '\s+')[0]) { throw 'Monitor checksum mismatch.' }
}
$power=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
. (Join-Path $PSScriptRoot 'ATTENTION-TASK-OWNERSHIP.ps1')
$existing=Get-ScheduledTask -TaskName 'CC health monitor' -ErrorAction SilentlyContinue
if ($existing -and !(Test-AttentionMonitorOwnership $existing $Repo $power)) { throw 'Unexpected monitor task ownership.' }
$principal=if ($existing) { $existing.Principal } else { $server.Principal }
if ($existing -and $existing.State -eq 'Running') { throw 'Monitor is running; retry after its current check finishes.' }
New-Item -ItemType Directory -Path $root -Force | Out-Null
foreach ($name in @('CC-MONITOR.py','CC-MONITOR.ps1')) { Copy-Item -LiteralPath (Join-Path $PSScriptRoot $name) -Destination $root -Force }
$power=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$action=New-ScheduledTaskAction -Execute $power -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$(Join-Path $root 'CC-MONITOR.ps1')`" -Repo `"$Repo`"" -WorkingDirectory $Repo
$trigger=New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 1)
$settings=New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName 'CC health monitor' -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
@{recovery_enabled=$false; version=1} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $root 'installed.json') -Encoding UTF8
& $power -NoProfile -NonInteractive -ExecutionPolicy Bypass -File (Join-Path $root 'CC-MONITOR.ps1') -Repo $Repo
if ($LASTEXITCODE -ne 0) { throw 'Monitor installed in observation mode; its first observation needs review.' }
Write-Host 'Observation monitor installed: every minute; automatic recovery disabled until activation.'
if ($principal.LogonType -eq 'Interactive') { Write-Host 'This account must remain signed in for monitoring to run.' }
