param([string]$Repo = 'C:\Users\Administrator\trading_bots\command-center')
$ErrorActionPreference = 'Stop'
$Repo = (Resolve-Path -LiteralPath $Repo).Path
$python = Join-Path $Repo '.venv\Scripts\python.exe'
if (!(Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Repository Python is missing.' }
$files = @('CC-MONITOR.py', 'CC-MONITOR.ps1', 'test_cc_monitor.py', 'CC-MONITOR.md')
foreach ($name in ($files + @('COLLECT-CC-REVIEW.py', 'COLLECT-CC-REVIEW.ps1', 'test_platform_enrich_probe.py'))) {
    $entry = @(Get-Content -LiteralPath (Join-Path $PSScriptRoot 'MONITOR-SHA256.txt') |
        Where-Object { $_ -match ('^[a-fA-F0-9]{64}\s+\*?' + [regex]::Escape($name) + '$') })
    if ($entry.Count -ne 1 -or (Get-FileHash -LiteralPath (Join-Path $PSScriptRoot $name) -Algorithm SHA256).Hash -ne ($entry[0] -split '\s+')[0]) {
        throw "Monitor payload checksum mismatch: $name"
    }
}
$server = Get-ScheduledTask -TaskName 'CC server' -ErrorAction Stop
if ($server.Actions.Count -ne 1 -or $server.Actions[0].Arguments -notmatch '-m\s+cc_server\.main\b' -or
    $server.Actions[0].WorkingDirectory.TrimEnd('\') -ne $Repo.TrimEnd('\')) { throw 'Unexpected server task ownership.' }
$root = Join-Path $Repo 'var\monitor'
$existing = Get-ScheduledTask -TaskName 'CC health monitor' -ErrorAction SilentlyContinue
if ($existing) {
    if ($existing.Actions.Count -ne 1 -or !$existing.Actions[0].Arguments.Contains((Join-Path $root 'CC-MONITOR.ps1'))) {
        throw 'The existing monitor task is not owned by this installer.'
    }
    if ($existing.State -eq 'Running') { Stop-ScheduledTask -TaskName 'CC health monitor' -ErrorAction Stop }
}
$sandbox = Join-Path $env:TEMP ('cc-monitor-tests-' + [guid]::NewGuid().ToString('N'))
try {
    & $python -B -m pytest -q (Join-Path $PSScriptRoot 'test_cc_monitor.py') (Join-Path $PSScriptRoot 'test_platform_enrich_probe.py') --basetemp $sandbox -o "cache_dir=$sandbox\cache"
    if ($LASTEXITCODE -ne 0) { throw 'Monitor regression tests failed.' }
} finally { Remove-Item -LiteralPath $sandbox -Recurse -Force -ErrorAction SilentlyContinue }
New-Item -ItemType Directory -Path $root -Force | Out-Null
foreach ($name in $files) { Copy-Item -LiteralPath (Join-Path $PSScriptRoot $name) -Destination (Join-Path $root $name) -Force }
$powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$monitor = Join-Path $root 'CC-MONITOR.ps1'
$action = New-ScheduledTaskAction -Execute $powershell -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$monitor`" -Repo `"$Repo`"" -WorkingDirectory $Repo
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(5) -RepetitionInterval (New-TimeSpan -Minutes 5)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 3)
Register-ScheduledTask -TaskName 'CC health monitor' -Action $action -Trigger $trigger -Settings $settings -Principal $server.Principal -Force | Out-Null

& $powershell -NoProfile -ExecutionPolicy Bypass -File $monitor -Repo $Repo
$observationExit = $LASTEXITCODE
Write-Host "CC health monitor installed: observations every five minutes. Initial check exit: $observationExit"
Write-Host "Current report: $root\latest.json"
Write-Host 'A nonzero observation exit reports issues; it does not undo installation or alter trading controls.'
Write-Host 'Only an enabled, stopped server can be started, with a 30-minute cooldown. Bot sessions are never started or restarted.'
if ($server.Principal.LogonType -eq 'Interactive') { Write-Host 'Monitor inherits the server account: remain signed in.' }

# Collect the current native evidence once, including new monitor JSONL logs.
# Full SQLite backup collection is deliberately NOT repeated every five minutes.
& $powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'COLLECT-CC-REVIEW.ps1') -Repo $Repo
if ($LASTEXITCODE -ne 0) { throw 'Monitor is installed, but initial review collection failed; retain the latest report.' }
