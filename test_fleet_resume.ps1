$ErrorActionPreference='Stop'
$path=Join-Path $PSScriptRoot 'FLEET-RESUME-HELPERS.ps1'
if (!(Test-Path -LiteralPath $path)) { throw 'No fleet resume orchestration exists.' }
. $path
$root=Join-Path ([IO.Path]::GetTempPath()) ('resume-test-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path (Join-Path $root 'var/monitor') -Force | Out-Null
try {
    $script:events=@();$script:state='Running';$script:monitorEnabled=$true;$script:fail=$false
    function Get-FleetResumeServer { param($Repo) [pscustomobject]@{State=$script:state} }
    function Get-FleetResumeMonitor { param($Repo,[switch]$AllowDisabled) [pscustomobject]@{State='Ready';Settings=[pscustomobject]@{Enabled=$script:monitorEnabled}} }
    function Get-ScheduledTask { param($TaskName,$TaskPath,$ErrorAction) if($TaskName -eq 'CC server'){[pscustomobject]@{State=$script:state}}else{[pscustomobject]@{State='Ready'}} }
    function Disable-ScheduledTask {param($TaskName,$TaskPath,$ErrorAction) $script:events+='disable_monitor';$script:monitorEnabled=$false}
    function Enable-ScheduledTask {param($TaskName,$TaskPath,$ErrorAction) $script:events+='enable_monitor';$script:monitorEnabled=$true}
    function Stop-ScheduledTask {param($TaskName,$TaskPath,$ErrorAction) if($TaskName -ne 'CC server'){throw 'Bot or monitor stopped'};$script:events+='stop_server';$script:state='Ready'}
    function Start-ScheduledTask {param($TaskName,$TaskPath,$ErrorAction) if($TaskName -ne 'CC server'){throw 'Bot task started'};$script:events+='start_server';$script:state='Running'}
    function Get-NetTCPConnection {param($LocalPort,$State,$ErrorAction) return @()}
    function Invoke-FleetResumePython {param($Repo,$ToolRoot,$Mode,$Receipt,[switch]$Approve) $script:events+=$Mode;if($Mode -eq 'apply' -and $script:fail){throw 'Refused mutation'};[pscustomobject]@{ok=$true}}
    function Wait-FleetResumeServer {param($Repo) $script:events+='verify_server'}
    $refused=$false;try { Invoke-FleetPaperResume -Repo $root -ToolRoot $PSScriptRoot } catch {$refused=$true}
    if(!$refused -or $script:events.Count){throw 'Unapproved operation changed tasks'}
    Invoke-FleetPaperResume -Repo $root -ToolRoot $PSScriptRoot -ApproveFleetPaperEntries | Out-Null
    if(($script:events -join ',') -ne 'disable_monitor,check,stop_server,apply,start_server,verify_server,verify,enable_monitor'){throw ('Wrong release order: '+($script:events -join ','))}
    $script:events=@();$script:fail=$true
    $refused=$false;try{Invoke-FleetPaperResume -Repo $root -ToolRoot $PSScriptRoot -ApproveFleetPaperEntries | Out-Null}catch{$refused=$true}
    if(!$refused -or $script:state -ne 'Running' -or !$script:monitorEnabled){throw 'Refused mutation stranded monitoring or server'}
    if($script:events -notcontains 'block'){throw 'Failed apply omitted fail-closed recovery'}
    Write-Host 'PASS: approval, release ordering, owned-server-only actions, and failure recovery.'
} finally {Remove-Item -LiteralPath $root -Recurse -Force}
