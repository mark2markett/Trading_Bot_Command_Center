function Assert-TradeReviewIdle {
    $processes=Get-CimInstance -ClassName Win32_Process -ErrorAction Stop
    foreach($process in $processes){
        if($process.Name -notmatch '^python(w)?\.exe$'){continue}
        if([string]::IsNullOrWhiteSpace($process.CommandLine)){
            throw 'A Python process cannot be inspected. Retry the review installation with bot commands idle.'
        }
        if($process.CommandLine -match 'bot\.py.*\b(session|decide|reconcile)\b'){
            throw 'A bot command is running. Install the review after commands finish; no process was stopped.'
        }
    }
    $tasks=Get-ScheduledTask -TaskName 'CC bot *' -ErrorAction Stop
    foreach($task in $tasks){
        if($task.State -eq 'Running'){throw 'A bot task is running. No task was started or stopped.'}
        $info=$task | Get-ScheduledTaskInfo -ErrorAction Stop
        if($info.NextRunTime){
            $seconds=($info.NextRunTime-(Get-Date)).TotalSeconds
            if($seconds -ge -5 -and $seconds -lt 300){throw 'A bot task is due within five minutes. Install outside its command window.'}
        }
    }
}
