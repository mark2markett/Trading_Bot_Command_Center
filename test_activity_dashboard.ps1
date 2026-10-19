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
    foreach ($scenario in @('success','apply_failure','rollback_failure')) {
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
    if (mode=='apply' and scenario!='owner checkout success') or (mode=='rollback' and scenario=='owner checkout rollback_failure'):sys.exit(1)
    print(json.dumps({'ok':True}))
'@
        [IO.File]::WriteAllText($pythonExe,$shim,[Text.UTF8Encoding]::new($false))
        & chmod +x $pythonExe
        $global:activityTestRepo=$repo
        $global:activityTestServer=[pscustomobject]@{State='Running';Settings=[pscustomobject]@{Enabled=$true};Actions=@([pscustomobject]@{Execute=$pythonExe;Arguments='-m cc_server.main';WorkingDirectory=$repo})}
        $monitorScript=Join-Path $repo 'var/monitor/CC-MONITOR.ps1'
        $global:activityTestMonitor=[pscustomobject]@{State='Ready';Settings=[pscustomobject]@{Enabled=$true};Actions=@([pscustomobject]@{Execute=$power;Arguments=('-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "'+$monitorScript+'" -Repo "'+$repo+'"');WorkingDirectory=$repo})}
        $global:activityTestStarts=0;$global:activityTestStops=0
        function Get-ScheduledTask { param($TaskName,$TaskPath,$ErrorAction) if($TaskName -eq 'CC server'){return $global:activityTestServer};if($TaskName -eq 'CC health monitor'){return $global:activityTestMonitor};throw 'Unowned task queried' }
        function Disable-ScheduledTask { param($TaskName,$TaskPath) if($TaskName -ne 'CC health monitor'){throw 'Unowned disable'};$global:activityTestMonitor.Settings.Enabled=$false }
        function Enable-ScheduledTask { param($TaskName,$TaskPath) if($TaskName -ne 'CC health monitor'){throw 'Unowned enable'};$global:activityTestMonitor.Settings.Enabled=$true }
        function Stop-ScheduledTask { param($TaskName,$TaskPath) if($TaskName -ne 'CC server'){throw 'Unowned stop'};$global:activityTestServer.State='Ready';$global:activityTestStops++ }
        function Start-ScheduledTask { param($TaskName,$TaskPath) if($TaskName -ne 'CC server'){throw 'Unowned start'};$global:activityTestServer.State='Running';$global:activityTestStarts++ }
        function Get-NetTCPConnection { param($LocalPort,$State,$ErrorAction) return }
        function Invoke-RestMethod { param($Uri,$TimeoutSec) return [pscustomobject]@{ok=$true;db=(Join-Path $global:activityTestRepo 'var/cc.db')} }
        $failed=$false
        try { & (Join-Path $toolRoot 'INSTALL-ACTIVITY-DASHBOARD.ps1') -Repo $repo } catch { $failed=$true; Write-Host ('Captured: '+$_.Exception.Message) }
        $calls=@(Get-Content (Join-Path $repo 'invocations.txt'))
        if ($scenario -eq 'success') {
            if ($failed -or ($calls -join ',') -ne 'prepare,apply,verify' -or $global:activityTestStarts -ne 1 -or !$global:activityTestMonitor.Settings.Enabled) { throw 'Success path failed' }
        } elseif ($scenario -eq 'apply_failure') {
            if (!$failed -or ($calls -join ',') -ne 'prepare,apply,rollback' -or $global:activityTestStarts -ne 1 -or !$global:activityTestMonitor.Settings.Enabled) { throw 'Apply recovery failed' }
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
