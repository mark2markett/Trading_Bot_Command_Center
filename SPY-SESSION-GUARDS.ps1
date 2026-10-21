function Assert-SpySessionIdle {
    param([string]$Repo)
    $expectedPython=(Resolve-Path -LiteralPath (Join-Path $Repo '.venv/Scripts/python.exe')).Path
    $expectedFolder=(Resolve-Path -LiteralPath (Join-Path $Repo 'bots/spy_mr_bot')).Path
    foreach($process in Get-CimInstance -ClassName Win32_Process -ErrorAction Stop){
        if($process.Name -notmatch '^python(w)?\.exe$'){continue}
        if([string]::IsNullOrWhiteSpace($process.CommandLine)){throw 'A Python process is uninspectable; SPY source update refused.'}
        if($process.CommandLine -match 'spy_mr_bot[\\/]' -or
           $process.CommandLine -match '(bot\.py|\s-m\s+bot\b).*\b(decide|reconcile)\b'){
            throw 'A daily bot command is running; SPY source update refused. No process was stopped.'
        }
    }
    foreach($command in @('decide','reconcile')){
        $task=Get-ScheduledTask -TaskName ('CC bot spy_mr_bot '+$command) -TaskPath '\' -ErrorAction Stop
        if($task.State -ne 'Ready' -or !$task.Settings.Enabled -or $task.Actions.Count -ne 1){throw 'SPY task is not idle and enabled; source update refused.'}
        $action=$task.Actions[0]
        if((Resolve-Path -LiteralPath $action.Execute.Trim('"')).Path -ne $expectedPython -or
           (Resolve-Path -LiteralPath $action.WorkingDirectory).Path -ne $expectedFolder -or
           $action.Arguments -notmatch ('^\s*(-u\s+)?bot\.py\s+'+$command+'\s*$')){
            throw 'SPY task ownership or action differs; source update refused.'
        }
        $info=$task | Get-ScheduledTaskInfo -ErrorAction Stop
        if(!$info.NextRunTime){throw 'SPY next-run time is unavailable; source update refused.'}
        $seconds=($info.NextRunTime-(Get-Date)).TotalSeconds
        if($seconds -lt 300){throw 'SPY next-run time is stale or within five minutes; source update refused.'}
    }
}
