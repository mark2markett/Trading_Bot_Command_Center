function Get-FleetResumeServer {
    param([string]$Repo)
    $task=Get-ScheduledTask -TaskName 'CC server' -TaskPath '\' -ErrorAction Stop
    $python=Join-Path $Repo '.venv\Scripts\python.exe'
    if ($task.State -notin @('Running','Ready') -or !$task.Settings.Enabled -or $task.Actions.Count -ne 1 -or
        (Resolve-Path -LiteralPath $task.Actions[0].Execute.Trim('"')).Path -ne $python -or
        $task.Actions[0].Arguments -notmatch '^\s*(-u\s+)?-m\s+cc_server\.main\s*$' -or
        $task.Actions[0].WorkingDirectory.TrimEnd('\') -ne $Repo.TrimEnd('\')) { throw 'Expected exact owned CC server task.' }
    return $task
}
function Get-FleetResumeMonitor {
    param([string]$Repo,[switch]$AllowDisabled)
    $task=Get-ScheduledTask -TaskName 'CC health monitor' -TaskPath '\' -ErrorAction Stop
    $power=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    if ((!$AllowDisabled -and !$task.Settings.Enabled) -or !(Test-AttentionMonitorOwnership $task $Repo $power)) { throw 'Owned enabled incident monitor required.' }
    return $task
}
function Invoke-FleetResumePython {
    param([string]$Repo,[string]$ToolRoot,[string]$Mode,[string]$Receipt,[switch]$Approve)
    $extra=@();if($Approve){$extra=@('--approve-fleet-paper-entries')}
    $raw=& (Join-Path $Repo '.venv\Scripts\python.exe') -B (Join-Path $ToolRoot 'FLEET-PAPER-RESUME.py') $Mode --repo $Repo --receipt $Receipt @extra
    if($LASTEXITCODE -ne 0){throw ('Fleet operation refused: '+($raw -join "`n"))}
    $value=($raw -join "`n") | ConvertFrom-Json
    if($value.ok -ne $true){throw 'Fleet operation did not verify success.'}
    return $value
}
function Wait-FleetResumeServer {
    param([string]$Repo)
    for($i=0;$i -lt 25;$i++){
        Get-FleetResumeServer $Repo | Out-Null
        try{
            $health=Invoke-RestMethod 'http://127.0.0.1:8585/api/health' -TimeoutSec 2
            if($health.ok -eq $true -and [IO.Path]::GetFullPath($health.db) -eq (Join-Path $Repo 'var\cc.db')){return}
        }catch{}
        Start-Sleep -Seconds 1
    }
    throw 'Server readiness unverified; preserve the receipt.'
}
function Invoke-FleetPaperResume {
    param([string]$Repo,[string]$ToolRoot,[switch]$ApproveFleetPaperEntries)
    if(!$ApproveFleetPaperEntries){throw 'Explicit -ApproveFleetPaperEntries is required; no controls changed.'}
    $Repo=(Resolve-Path -LiteralPath $Repo).Path
    $lock=$null;$restoreMonitor=$false;$restart=$false;$applyAttempted=$false
    $receipt=Join-Path $Repo ('var\backups\fleet-resume-'+[guid]::NewGuid().ToString('N')+'.json')
    try{
        $lock=[IO.File]::Open((Join-Path $Repo 'var\monitor\holding-install.lock'),[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
        if((Get-FleetResumeServer $Repo).State -ne 'Running'){throw 'Resume requires the owned running server.'}
        Get-FleetResumeMonitor $Repo | Out-Null
        Disable-ScheduledTask -TaskName 'CC health monitor' -TaskPath '\' -ErrorAction Stop | Out-Null
        $restoreMonitor=$true
        for($i=0;$i -lt 30;$i++){
            if((Get-ScheduledTask -TaskName 'CC health monitor' -TaskPath '\' -ErrorAction Stop).State -ne 'Running'){break}
            Start-Sleep -Seconds 1
        }
        if((Get-ScheduledTask -TaskName 'CC health monitor' -TaskPath '\' -ErrorAction Stop).State -eq 'Running'){throw 'Monitor is still checking; no control changed.'}
        New-Item -ItemType Directory -Path (Split-Path $receipt) -Force | Out-Null
        Invoke-FleetResumePython -Repo $Repo -ToolRoot $ToolRoot -Mode check -Receipt $receipt | Out-Null
        Write-Host ('Fleet resume receipt: '+$receipt)
        Get-FleetResumeServer $Repo | Out-Null
        $restart=$true
        Stop-ScheduledTask -TaskName 'CC server' -TaskPath '\' -ErrorAction Stop
        for($i=0;$i -lt 20;$i++){
            if((Get-ScheduledTask -TaskName 'CC server' -TaskPath '\' -ErrorAction Stop).State -eq 'Ready' -and !(Get-NetTCPConnection -LocalPort 8585 -State Listen -ErrorAction SilentlyContinue)){break}
            Start-Sleep -Seconds 1
        }
        if((Get-ScheduledTask -TaskName 'CC server' -TaskPath '\' -ErrorAction Stop).State -ne 'Ready' -or (Get-NetTCPConnection -LocalPort 8585 -State Listen -ErrorAction SilentlyContinue)){throw 'Server did not quiesce; no process forced to stop.'}
        $applyAttempted=$true
        $result=Invoke-FleetResumePython -Repo $Repo -ToolRoot $ToolRoot -Mode apply -Receipt $receipt -Approve
        Get-FleetResumeServer $Repo | Out-Null
        Start-ScheduledTask -TaskName 'CC server' -TaskPath '\' -ErrorAction Stop
        $restart=$false
        Wait-FleetResumeServer $Repo
        Invoke-FleetResumePython -Repo $Repo -ToolRoot $ToolRoot -Mode verify -Receipt $receipt | Out-Null
        return $result
    }catch{
        $failure=$_.Exception.Message
        if($applyAttempted){
            try{Invoke-FleetResumePython -Repo $Repo -ToolRoot $ToolRoot -Mode block -Receipt $receipt | Out-Null}
            catch{Write-Warning ('Could not verify fail-closed pause: '+$_.Exception.Message)}
        }
        throw ($failure+' Receipt: '+$receipt)
    }finally{
        try{
            if($restart -and (Get-FleetResumeServer $Repo).State -eq 'Ready'){
                Start-ScheduledTask -TaskName 'CC server' -TaskPath '\' -ErrorAction Stop
            }
        }finally{
            try{if($restoreMonitor){Get-FleetResumeMonitor $Repo -AllowDisabled | Out-Null;Enable-ScheduledTask -TaskName 'CC health monitor' -TaskPath '\' -ErrorAction Stop | Out-Null}}
            finally{if($lock){$lock.Dispose()}}
        }
    }
}
