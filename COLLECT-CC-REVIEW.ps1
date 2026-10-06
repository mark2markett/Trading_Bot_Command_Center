param([string]$Repo = 'C:\Users\Administrator\trading_bots\command-center')
$ErrorActionPreference = 'Stop'
$Repo = (Resolve-Path -LiteralPath $Repo).Path
$python = Join-Path $Repo '.venv\Scripts\python.exe'
if (!(Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Repository Python is missing.' }
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$review = Join-Path $env:TEMP ('CC-review-' + $stamp + '-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $review | Out-Null
& $python -B (Join-Path $PSScriptRoot 'COLLECT-CC-REVIEW.py') $Repo $review
if ($LASTEXITCODE -ne 0) { throw "Evidence collection failed. Retained files: $review" }
$runtime = Join-Path $Repo 'var'
if ($env:CC_VAR) { $runtime = $env:CC_VAR }
$logDir = Join-Path $review 'logs'
New-Item -ItemType Directory -Path $logDir | Out-Null
Get-ChildItem -LiteralPath (Join-Path $runtime 'logs') -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -match '\.(log|jsonl)(\.\d+)?$' } |
    Copy-Item -Destination $logDir
$daily = Join-Path $Repo 'bots\spy_mr_bot\bot.log'
if (Test-Path -LiteralPath $daily) { Copy-Item -LiteralPath $daily -Destination (Join-Path $review 'spy-mr.log') }
Get-ScheduledTask -TaskName 'CC *' | ForEach-Object {
    $info = $_ | Get-ScheduledTaskInfo
    [pscustomobject]@{
        Task=$_.TaskName; State=$_.State; LastRun=$info.LastRunTime
        Result=('0x{0:X}' -f $info.LastTaskResult); NextRun=$info.NextRunTime
        ExecutionTimeLimit=$_.Settings.ExecutionTimeLimit
        RestartCount=$_.Settings.RestartCount; RestartInterval=$_.Settings.RestartInterval
        StopIfGoingOnBatteries=$_.Settings.StopIfGoingOnBatteries
        DisallowStartIfOnBatteries=$_.Settings.DisallowStartIfOnBatteries
        LogonType=$_.Principal.LogonType
    }
} | Export-Csv (Join-Path $review 'tasks.csv') -NoTypeInformation -Encoding UTF8
try {
    Get-WinEvent -FilterHashtable @{
        LogName='Microsoft-Windows-TaskScheduler/Operational'
        StartTime=(Get-Date).Date.AddDays(-1)
    } -ErrorAction Stop |
        Where-Object { $_.Message -match 'CC (bot |server|backup)' } |
        Select-Object TimeCreated, Id, RecordId, Message |
        Export-Csv (Join-Path $review 'task-history.csv') -NoTypeInformation -Encoding UTF8
} catch {
    'Task history unavailable; no new scheduler setting was changed by this collector.' |
        Set-Content (Join-Path $review 'task-history-status.txt')
}
Push-Location -LiteralPath $Repo
try {
    git branch --show-current | Set-Content (Join-Path $review 'source.txt')
    git log -1 --format='%H %s' | Add-Content (Join-Path $review 'source.txt')
    git status --short | Set-Content (Join-Path $review 'source-status.txt')
} finally { Pop-Location }
$zip = Join-Path ([Environment]::GetFolderPath('Desktop')) ('CC-review-' + $stamp + '.zip')
Compress-Archive -Path (Join-Path $review '*') -DestinationPath $zip -ErrorAction Stop
Write-Host "Upload this review ZIP here: $zip"
Write-Host 'No environment/token files, orders, controls, source, task settings, or capital were changed.'
