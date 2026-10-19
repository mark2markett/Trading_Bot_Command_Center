[CmdletBinding()]
param([string]$Repo='C:\Users\Administrator\trading_bots\command-center',[switch]$ApproveFleetPaperEntries)
$ErrorActionPreference='Stop'
if(!$ApproveFleetPaperEntries){throw 'Explicit fleet paper-entry approval required; SIP remains paused.'}
$Repo=(Resolve-Path -LiteralPath $Repo).Path
foreach($line in Get-Content -LiteralPath (Join-Path $PSScriptRoot 'FLEET-RESUME-SHA256.txt')){
    if($line -notmatch '^([a-f0-9]{64})\s+([A-Za-z0-9_.-]+)$'){throw 'Invalid release checksum entry.'}
    if((Get-FileHash -LiteralPath (Join-Path $PSScriptRoot $Matches[2])).Hash -ne $Matches[1]){throw 'Release checksum mismatch.'}
}
$failure=$null
try{
    $raw=& (Join-Path $PSScriptRoot 'RESUME-FLEET-PAPER.ps1') -Repo $Repo -ApproveFleetPaperEntries
    $raw | Write-Output
    $result=($raw -join "`n") | ConvertFrom-Json
    if($result.ok -ne $true -or $result.resumed -ne $true -or $result.sip_paused -ne $true){throw 'Fleet release did not verify the approved outcome.'}
}catch{
    $failure=$_.Exception.Message
    Write-Host ('RELEASE NOT CONFIRMED: '+$failure)
}
Write-Host 'CURRENT READ-ONLY EVIDENCE:'
$diagnostic=& (Join-Path $Repo '.venv\Scripts\python.exe') -B (Join-Path $PSScriptRoot 'DIAGNOSE-FLEET-BLOCKERS.py') --repo $Repo
$diagnosticExit=$LASTEXITCODE
$diagnostic | Write-Output
if($diagnosticExit -ne 0){throw 'Diagnostic collection is incomplete; paste the preceding output.'}
$observed=($diagnostic -join "`n") | ConvertFrom-Json
if($observed.collection_complete -ne $true){throw 'Current evidence is incomplete; paste the preceding output.'}
if($failure){throw 'Fleet release remains blocked. Paste the complete output above.'}
if($observed.fleet_entries_paused -ne $false){throw 'Current evidence still shows a fleet pause; paste the preceding output.'}
Write-Host 'Fleet release verified. SIP remains paused; current SIP evidence is printed above.'
