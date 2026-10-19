param(
    [string]$Repo='C:\Users\Administrator\trading_bots\command-center',
    [switch]$Apply,[switch]$Rollback,[string]$Receipt
)
$ErrorActionPreference='Stop'
if ($env:OS -ne 'Windows_NT') { throw 'This operator helper requires Windows Task Scheduler.' }
$Repo=(Resolve-Path -LiteralPath $Repo -ErrorAction Stop).Path
foreach ($line in Get-Content -LiteralPath (Join-Path $PSScriptRoot 'WEEKDAY-TASKS-SHA256.txt')) {
    if ($line -notmatch '^([a-f0-9]{64})\s+([A-Za-z0-9_.-]+)$') { throw 'Invalid weekday repair checksum entry.' }
    if ((Get-FileHash -LiteralPath (Join-Path $PSScriptRoot $Matches[2])).Hash -ne $Matches[1]) { throw 'Weekday repair checksum mismatch.' }
}
. (Join-Path $PSScriptRoot 'WEEKDAY-TASK-HELPERS.ps1')
Invoke-WeekdayTaskRepair -Repo $Repo -ToolRoot $PSScriptRoot -Apply:$Apply -Rollback:$Rollback -Receipt $Receipt |
    ConvertTo-Json -Depth 6
