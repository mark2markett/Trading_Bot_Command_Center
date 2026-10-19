[CmdletBinding()]
param([string]$Repo='C:\Users\Administrator\trading_bots\command-center',[switch]$ApproveFleetPaperEntries)
$ErrorActionPreference='Stop'
if($env:OS -ne 'Windows_NT'){throw 'This owner operation requires Windows Task Scheduler.'}
foreach($line in Get-Content -LiteralPath (Join-Path $PSScriptRoot 'FLEET-RESUME-SHA256.txt')){
    if($line -notmatch '^([a-f0-9]{64})\s+([A-Za-z0-9_.-]+)$'){throw 'Invalid fleet resume checksum entry.'}
    if((Get-FileHash -LiteralPath (Join-Path $PSScriptRoot $Matches[2])).Hash -ne $Matches[1]){throw 'Fleet resume checksum mismatch.'}
}
. (Join-Path $PSScriptRoot 'ATTENTION-TASK-OWNERSHIP.ps1')
. (Join-Path $PSScriptRoot 'FLEET-RESUME-HELPERS.ps1')
Invoke-FleetPaperResume -Repo $Repo -ToolRoot $PSScriptRoot -ApproveFleetPaperEntries:$ApproveFleetPaperEntries | ConvertTo-Json -Depth 5
