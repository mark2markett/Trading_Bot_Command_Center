param([string]$Python='/workspace/.venv-readiness/bin/python')
$ErrorActionPreference='Stop'
$toolRoot=$PSScriptRoot
$testRoot=Join-Path ([IO.Path]::GetTempPath()) ('activity-ps-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory $testRoot | Out-Null
$priorSystemRoot=$env:SystemRoot
try {
    $env:SystemRoot=Join-Path $testRoot 'Windows'
    $power=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    New-Item -ItemType Directory (Split-Path $power) -Force | Out-Null
    Set-Content -LiteralPath $power -Value 'test executable identity'
    foreach ($scenario in @('success','delayed_stop','stuck_stop','health_failure','busy_before_apply','busy_before_rollback','apply_failure','rollback_failure')) {
        $repo=Join-Path $testRoot ('owner checkout '+$scenario)
        New-Item -ItemType Directory (Join-Path $repo 'var/monitor') -Force | Out-Null
        New-Item -ItemType Directory (Join-Path $repo '.venv/Scripts') -Force | Out-Null
        $pythonExe=Join-Path $repo '.venv/Scripts/python.exe'
        $shim=@'
#!/usr/bin/env python3
import json,os,sys
from pathlib import Path
mode=sys.argv[3]
root=Path(sys.argv[sys.argv.index('--repo')+1])
with (root/'invocations.txt').open('a') as f:f.write(mode+'\n')
scenario=root.name
if mode=='prepare': print(json.dumps({'ok':True,'receipt':str(root/'var/backups/activity-dashboard-test')}))
else:
    if (mode=='apply' and scenario not in ('owner checkout success','owner checkout delayed_stop','owner checkout health_failure','owner checkout busy_before_rollback')) or (mode=='rollback' and scenario=='owner checkout rollback_failure'):sys.exit(1)
    print(json.dumps({'ok':True}))
'@
        [IO.File]::WriteAllText($pythonExe,$shim,[Text.UTF8Encoding]::new($false))
        & chmod +x $pythonExe
        $global:activityTestRepo=$repo
        $global:activityTestServer=[pscustomobject]@{State='Running';Settings=[pscustomobject]@{Enabled=$true};Actions=@([pscustomobject]@{Execute=$pythonExe;Arguments='-m cc_server.main';WorkingDirectory=$repo})}
        $monitorScript=Join-Path $repo 'var/monitor/CC-MONITOR.ps1'
        $global:activityTestMonitor=[pscustomobject]@{State='Ready';Settings=[pscustomobject]@{Enabled=$true};Actions=@([pscustomobject]@{Execute=$power;Arguments=('-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "'+$monitorScript+'" -Repo "'+$repo+'"');WorkingDirectory=$repo})}
        $global:activityTestStarts=0;$global:activityTestStops=0;$global:activityStopPending=0
        $global:activityDelayedStop=($scenario -eq 'delayed_stop')
        $global:activityStuckStop=($scenario -eq 'stuck_stop')
        $global:activityHealthFailure=($scenario -in @('health_failure','busy_before_rollback'))
        $global:activityBusyBeforeApply=($scenario -eq 'busy_before_apply')
        $global:activityBusyBeforeRollback=($scenario -eq 'busy_before_rollback')
        function Start-Sleep { param($Seconds) }
        function Get-ScheduledTask {
            param($TaskName,$TaskPath,$ErrorAction)
            if($TaskName -eq 'CC server'){
                if($global:activityStopPending -gt 0){
                    $global:activityStopPending--
                    if($global:activityStopPending -eq 0){$global:activityTestServer.State='Ready'}
                }
                return $global:activityTestServer
            }
            if($TaskName -eq 'CC health monitor'){return $global:activityTestMonitor}
            if($TaskName -eq 'CC bot *'){return @()}
            throw 'Unowned task queried'
        }
        function Get-CimInstance {
            param($ClassName,$ErrorAction)
            if(($global:activityBusyBeforeApply -and $global:activityTestStops -gt 0) -or ($global:activityBusyBeforeRollback -and $global:activityTestStarts -gt 0)){
                return [pscustomobject]@{Name='python.exe';CommandLine='python.exe bot.py session'}
            }
            return @()
        }
        function Disable-ScheduledTask { param($TaskName,$TaskPath) if($TaskName -ne 'CC health monitor'){throw 'Unowned disable'};$global:activityTestMonitor.Settings.Enabled=$false }
        function Enable-ScheduledTask { param($TaskName,$TaskPath) if($TaskName -ne 'CC health monitor'){throw 'Unowned enable'};$global:activityTestMonitor.Settings.Enabled=$true }
        function Stop-ScheduledTask {
            param($TaskName,$TaskPath)
            if($TaskName -ne 'CC server'){throw 'Unowned stop'}
            if($global:activityStuckStop){$global:activityTestServer.State='Running'}
            elseif($global:activityDelayedStop){$global:activityStopPending=2}
            else{$global:activityTestServer.State='Ready'}
            $global:activityTestStops++
        }
        function Start-ScheduledTask {
            param($TaskName,$TaskPath)
            if($TaskName -ne 'CC server'){throw 'Unowned start'}
            # Task Scheduler IgnoreNew silently ignores a start until stop has completed.
            if($global:activityTestServer.State -ne 'Ready'){return}
            $global:activityTestServer.State='Running';$global:activityTestStarts++
        }
        function Get-NetTCPConnection { param($LocalPort,$State,$ErrorAction) return }
        function Get-ScheduledTaskInfo { param($TaskName,$TaskPath) return [pscustomobject]@{LastTaskResult=1} }
        function Invoke-RestMethod {
            param($Uri,$TimeoutSec)
            if($global:activityTestStarts -eq 0){throw 'No candidate server was started'}
            if($global:activityHealthFailure -and $global:activityTestStarts -eq 1){throw 'Simulated failed candidate health'}
            return [pscustomobject]@{ok=$true;db=(Join-Path $global:activityTestRepo 'var/cc.db')}
        }
        $failed=$false;$failureMessage=''
        try { & (Join-Path $toolRoot 'INSTALL-ACTIVITY-DASHBOARD.ps1') -Repo $repo } catch { $failed=$true;$failureMessage=$_.Exception.Message; Write-Host ('Captured: '+$failureMessage) }
        $calls=@(Get-Content (Join-Path $repo 'invocations.txt'))
        if ($scenario -in @('success','delayed_stop')) {
            if ($failed -or ($calls -join ',') -ne 'prepare,apply,verify' -or $global:activityTestStarts -ne 1 -or !$global:activityTestMonitor.Settings.Enabled) { throw 'Success path failed' }
        } elseif ($scenario -eq 'stuck_stop') {
            if (!$failed -or ($calls -join ',') -ne 'prepare' -or $global:activityTestStarts -ne 0 -or !$global:activityTestMonitor.Settings.Enabled) { throw 'Unstopped task was modified or restarted' }
        } elseif ($scenario -eq 'busy_before_apply') {
            if(!$failed -or ($calls -join ',') -ne 'prepare' -or $global:activityTestStarts -ne 1 -or !$global:activityTestMonitor.Settings.Enabled){throw 'Busy bot was overwritten during apply'}
        } elseif ($scenario -eq 'busy_before_rollback') {
            if(!$failed -or ($calls -join ',') -ne 'prepare,apply' -or $global:activityTestMonitor.Settings.Enabled){throw 'Busy bot was overwritten during rollback'}
        } elseif ($scenario -eq 'apply_failure') {
            if (!$failed -or ($calls -join ',') -ne 'prepare,apply,rollback' -or $global:activityTestStarts -ne 1 -or !$global:activityTestMonitor.Settings.Enabled) { throw 'Apply recovery failed' }
        } elseif ($scenario -eq 'health_failure') {
            if (!$failed -or ($calls -join ',') -ne 'prepare,apply,rollback' -or $global:activityTestStarts -ne 2 -or !$global:activityTestMonitor.Settings.Enabled) { throw 'Health failure recovery failed' }
            if ($failureMessage -notmatch 'task=Running; result=1; request=RuntimeException') { throw 'Health failure omitted safe startup evidence' }
        } else {
            if (!$failed -or ($calls -join ',') -ne 'prepare,apply,rollback' -or $global:activityTestStarts -ne 0 -or $global:activityTestMonitor.Settings.Enabled) { throw 'Unverified restoration was restarted' }
        }
        $lock=[IO.File]::Open((Join-Path $repo 'var/monitor/holding-install.lock'),[IO.FileMode]::Open,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None);$lock.Dispose()
        Write-Host ($scenario+': passed')
    }
} finally {
    $env:SystemRoot=$priorSystemRoot
    Remove-Item -LiteralPath $testRoot -Recurse -Force
}
