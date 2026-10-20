$ErrorActionPreference='Stop'
$root=Join-Path ([IO.Path]::GetTempPath()) ('operations-ps-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory $root | Out-Null
$priorSystemRoot=$env:SystemRoot
try {
    $env:SystemRoot=Join-Path $root 'Windows'
    $power=Join-Path $env:SystemRoot 'System32/WindowsPowerShell/v1.0/powershell.exe'
    New-Item -ItemType Directory (Split-Path $power) -Force | Out-Null
    Set-Content $power 'isolated executable identity'
    foreach($scenario in @('healthy','hung_api','monitor_busy','wrong_owner','stuck_stop','install_failure','prepare_failure')) {
        $dir=Join-Path $root $scenario;$repo=Join-Path $dir 'owner checkout';$package=Join-Path $dir 'package'
        New-Item -ItemType Directory (Join-Path $repo '.venv/Scripts') -Force | Out-Null
        New-Item -ItemType Directory (Join-Path $repo 'var/monitor') -Force | Out-Null
        New-Item -ItemType Directory $package -Force | Out-Null
        Copy-Item (Join-Path $PSScriptRoot 'REPAIR-OPERATIONS.ps1') $package
        Copy-Item (Join-Path $PSScriptRoot 'ATTENTION-TASK-OWNERSHIP.ps1') $package
        Set-Content (Join-Path $package 'OPERATIONS-REPAIR.py') '# isolated helper boundary'
        $shim=@'
#!/usr/bin/env python3
import json,sys
from pathlib import Path
mode=sys.argv[3];repo=Path(sys.argv[sys.argv.index('--repo')+1])
with (repo/'calls.txt').open('a') as out:out.write(mode+'\n')
if repo.parent.name=='prepare_failure':raise SystemExit(1)
print(json.dumps({'ok':True,'receipt':str(repo/'operations-repair-test.json')}))
'@
        $python=Join-Path $repo '.venv/Scripts/python.exe'
        [IO.File]::WriteAllText($python,$shim,[Text.UTF8Encoding]::new($false)); & chmod +x $python
        $install=@'
param($Repo)
Add-Content (Join-Path $Repo 'calls.txt') 'install'
if ((Split-Path (Split-Path $Repo) -Leaf) -eq 'monitor_busy') { $global:opMonitor.State='Running';$global:opBusyPolls=2 }
if ((Split-Path (Split-Path $Repo) -Leaf) -eq 'install_failure') { throw 'simulated source installation failure' }
'@
        [IO.File]::WriteAllText((Join-Path $package 'ENFORCE-OPTIONS-ONLY.ps1'),$install)
        $lines=foreach($name in @('REPAIR-OPERATIONS.ps1','OPERATIONS-REPAIR.py','ATTENTION-TASK-OWNERSHIP.ps1','ENFORCE-OPTIONS-ONLY.ps1')) {
            (Get-FileHash (Join-Path $package $name)).Hash.ToLower()+'  '+$name
        }
        Set-Content (Join-Path $package 'OPERATIONS-SHA256.txt') $lines
        $global:opRepo=$repo;$global:opScenario=$scenario;$global:opHealthy=($scenario -notin @('hung_api','stuck_stop'))
        $global:opStops=0;$global:opStarts=0;$global:opChecks=0;$global:opBusyPolls=0;$global:opSleeps=0
        $execute=if($scenario -eq 'wrong_owner'){$power}else{$python}
        $global:opServer=[pscustomobject]@{State='Running';Settings=[pscustomobject]@{Enabled=$true};Actions=@([pscustomobject]@{Execute=$execute;Arguments='-m cc_server.main';WorkingDirectory=$repo})}
        $global:opMonitor=[pscustomobject]@{State='Ready';Settings=[pscustomobject]@{Enabled=$true};Actions=@([pscustomobject]@{Execute=$power;Arguments=('-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "'+(Join-Path $repo 'var/monitor/CC-MONITOR.ps1')+'" -Repo "'+$repo+'"');WorkingDirectory=$repo})}
        function Get-ScheduledTask {param($TaskName,$TaskPath,$ErrorAction) if($TaskName -eq 'CC server'){return $global:opServer};if($TaskName -eq 'CC health monitor'){if($global:opBusyPolls -gt 0){$global:opBusyPolls--;if($global:opBusyPolls -eq 0){$global:opMonitor.State='Ready'}};return $global:opMonitor};throw 'Unowned task requested'}
        function Disable-ScheduledTask {param($TaskName,$TaskPath) if($TaskName -ne 'CC health monitor'){throw 'Unowned disable'};$global:opMonitor.Settings.Enabled=$false}
        function Enable-ScheduledTask {param($TaskName,$TaskPath) if($TaskName -ne 'CC health monitor'){throw 'Unowned enable'};$global:opMonitor.Settings.Enabled=$true}
        function Stop-ScheduledTask {param($TaskName,$TaskPath) if($TaskName -ne 'CC server'){throw 'Bot stop forbidden'};$global:opStops++;if($global:opScenario -ne 'stuck_stop'){$global:opServer.State='Ready'}}
        function Start-ScheduledTask {param($TaskName,$TaskPath) if($TaskName -eq 'CC server'){$global:opStarts++;$global:opServer.State='Running';$global:opHealthy=$true}elseif($TaskName -eq 'CC health monitor'){$global:opChecks++}else{throw 'Bot start forbidden'}}
        function Get-NetTCPConnection {param($LocalPort,$State,$ErrorAction) if($global:opScenario -eq 'stuck_stop'){return [pscustomobject]@{OwningProcess=123}}}
        function Start-Sleep {param($Seconds) $global:opSleeps++;if($global:opScenario -eq 'monitor_busy' -and $global:opSleeps -gt 4 -and $global:opChecks -eq 0){throw 'No fresh check was started after overlapping monitor tick'}}
        function Invoke-RestMethod {
            param($Uri,$TimeoutSec)
            if($Uri -like '*/health') {
                if(!$global:opHealthy){throw 'simulated API timeout'}
                return [pscustomobject]@{ok=$true;db=(Join-Path $global:opRepo 'var/cc.db')}
            }
            if($Uri -like '*/incidents?limit=1' -and $global:opScenario -eq 'monitor_busy' -and $global:opChecks -eq 0){return [pscustomobject]@{monitor=[pscustomobject]@{status='checking';last_completed_at=[DateTimeOffset]::UtcNow.AddMinutes(-1).ToString('o')}}}
            if($Uri -like '*/incidents?limit=1'){return [pscustomobject]@{monitor=[pscustomobject]@{status='checking';last_completed_at=[DateTimeOffset]::UtcNow.ToString('o')}}}
            throw 'Unexpected HTTP route'
        }
        $failed=$false
        try { & (Join-Path $package 'REPAIR-OPERATIONS.ps1') -Repo $repo } catch {$failed=$true;Write-Host ('Captured '+$scenario+': '+$_.Exception.Message)}
        $calls=(Get-Content (Join-Path $repo 'calls.txt')) -join ','
        if($scenario -in @('healthy','hung_api','monitor_busy')) {
            if($failed -or $calls -ne 'prepare,install,verify' -or $global:opChecks -ne 1){throw ('Success path wrong: '+$scenario+' '+$calls)}
            if($scenario -eq 'hung_api' -and ($global:opStops -ne 1 -or $global:opStarts -ne 1)){throw 'Owned API recovery was not performed once'}
            if($scenario -eq 'healthy' -and $global:opStops -ne 0){throw 'Healthy server unnecessarily restarted before install'}
        } elseif($scenario -eq 'install_failure') {
            if(!$failed -or $calls -ne 'prepare,install' -or $global:opStops -ne 0){throw 'Installation failure boundary wrong'}
        } else {
            if(!$failed -or $calls -ne 'prepare' -or $global:opStarts -ne 0){throw 'Refusal boundary wrong'}
        }
        if(!$global:opMonitor.Settings.Enabled){throw 'Prior monitor enabled state was not restored'}
    }
    Write-Host 'PASS: seven guarded operations recovery and failure scenarios.'
} finally {$env:SystemRoot=$priorSystemRoot;Remove-Item $root -Recurse -Force}
