# Only task scheduling metadata is handled here. No bot or broker code is imported.
function Get-WeekdayTaskNames {
    return [ordered]@{
        'CC bot gap_go_bot session'=@('gap_go_bot','session','09:25')
        'CC bot gap_go_spread_bot session'=@('gap_go_spread_bot','session','09:25')
        'CC bot nr7_bot session'=@('nr7_bot','session','09:25')
        'CC bot sip_orb session'=@('sip_orb','session','09:25')
        'CC bot spy_mr_bot decide'=@('spy_mr_bot','decide','15:50')
        'CC bot spy_mr_bot reconcile'=@('spy_mr_bot','reconcile','09:45')
    }
}
function Get-WeekdayTextHash {
    param([string]$Text)
    $sha=[Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($Text)))).Replace('-','').ToLowerInvariant() }
    finally { $sha.Dispose() }
}
function Get-WeekdayNodeText {
    param($Node,[string]$Path,$Namespace,[string]$Default='')
    $value=$Node.SelectSingleNode($Path,$Namespace)
    if ($null -eq $value) { return $Default }
    return $value.InnerText
}
function Get-WeekdayTaskPlan {
    param([string]$Xml,[string]$Name,[string]$Repo)
    $spec=Get-WeekdayTaskNames
    if (!$spec.Contains($Name)) { throw 'Unexpected bot task name.' }
    if ($Xml.Length -gt 1048576) { throw 'Task definition is unexpectedly large.' }
    $doc=New-Object System.Xml.XmlDocument
    $doc.XmlResolver=$null;$doc.LoadXml($Xml)
    $ns=New-Object System.Xml.XmlNamespaceManager($doc.NameTable)
    $ns.AddNamespace('t','http://schemas.microsoft.com/windows/2004/02/mit/task')
    if ($doc.DocumentElement.LocalName -ne 'Task' -or $doc.DocumentElement.NamespaceURI -ne $ns.LookupNamespace('t')) { throw 'Unexpected task schema.' }
    $actions=@($doc.SelectNodes('/t:Task/t:Actions/*',$ns))
    $entry=$doc.SelectSingleNode('/t:Task/t:Actions/t:Exec',$ns)
    if ($actions.Count -ne 1 -or !$entry) { throw 'Task action is not a single owned Python command.' }
    $folder,$command,$clock=$spec[$Name]
    $python=(Resolve-Path -LiteralPath (Join-Path $Repo '.venv/Scripts/python.exe')).Path
    $work=(Resolve-Path -LiteralPath (Join-Path $Repo ('bots/'+$folder))).Path
    $execute=Get-WeekdayNodeText $entry 't:Command' $ns
    $arguments=Get-WeekdayNodeText $entry 't:Arguments' $ns
    $directory=Get-WeekdayNodeText $entry 't:WorkingDirectory' $ns
    try {
        $owned=([IO.Path]::GetFullPath($execute.Trim('"')) -eq $python -and
            [IO.Path]::GetFullPath($directory.Trim('"')).TrimEnd([char[]]'\/') -eq $work.TrimEnd([char[]]'\/'))
    } catch { throw 'Task executable or working directory is not owned.' }
    if (!$owned -or $arguments -notmatch ('^\s*(?:-u\s+)?bot\.py\s+'+$command+'\s*$')) { throw 'Task action differs from the known bot command.' }
    $triggers=@($doc.SelectNodes('/t:Task/t:Triggers/*',$ns))
    if ($triggers.Count -ne 1 -or $triggers[0].LocalName -ne 'CalendarTrigger') { throw 'Expected one calendar trigger.' }
    $tr=$triggers[0]
    if ($tr.SelectSingleNode('t:Repetition|t:EndBoundary',$ns)) { throw 'Custom repetition or end boundary requires separate review.' }
    $allowed=@('StartBoundary','Enabled','ExecutionTimeLimit','RandomDelay','ScheduleByDay','ScheduleByWeek')
    if (@($tr.ChildNodes | Where-Object { $_.LocalName -notin $allowed }).Count) { throw 'Unexpected calendar trigger properties.' }
    $start=Get-WeekdayNodeText $tr 't:StartBoundary' $ns
    if ($start -notmatch ('^\d{4}-\d{2}-\d{2}T'+$clock+':00(?:-04:00|-05:00)?$')) { throw 'Task start time differs from its reviewed cadence.' }
    [datetime]::ParseExact($start.Substring(0,19),'yyyy-MM-ddTHH:mm:ss',[Globalization.CultureInfo]::InvariantCulture) | Out-Null
    $enabledText=Get-WeekdayNodeText $tr 't:Enabled' $ns 'true'
    if ($enabledText -notin @('true','false')) { throw 'Invalid trigger enabled state.' }
    $delay=Get-WeekdayNodeText $tr 't:RandomDelay' $ns 'PT0S'
    if ($delay -notin @('','PT0S')) { throw 'Randomized bot start requires separate review.' }
    $daily=$tr.SelectSingleNode('t:ScheduleByDay',$ns);$weekly=$tr.SelectSingleNode('t:ScheduleByWeek',$ns)
    if ($daily -and !$weekly -and (Get-WeekdayNodeText $daily 't:DaysInterval' $ns) -eq '1' -and $daily.ChildNodes.Count -eq 1) { $mode='daily' }
    elseif ($weekly -and !$daily) {
        $days=@($weekly.SelectNodes('t:DaysOfWeek/*',$ns) | ForEach-Object { $_.LocalName } | Sort-Object)
        if ((Get-WeekdayNodeText $weekly 't:WeeksInterval' $ns) -ne '1' -or $weekly.ChildNodes.Count -ne 2 -or ($days -join ',') -ne 'Friday,Monday,Thursday,Tuesday,Wednesday') { throw 'Unexpected weekly schedule.' }
        $mode='weekly'
    } else { throw 'Expected a daily or Monday-Friday weekly schedule.' }
    $protected=''
    foreach ($path in @('Actions','Principals','Settings','Data')) {
        $node=$doc.SelectSingleNode('/t:Task/t:'+$path,$ns)
        if ($node) { $protected+=$node.OuterXml }
    }
    return [pscustomobject]@{
        Name=$Name;Mode=$mode;Start=$start;Enabled=($enabledText -eq 'true')
        TriggerId=$tr.GetAttribute('id');ExecutionTimeLimit=(Get-WeekdayNodeText $tr 't:ExecutionTimeLimit' $ns 'PT72H')
        RandomDelay=$delay;ProtectedHash=(Get-WeekdayTextHash $protected)
        Xml=$doc.OuterXml;XmlHash=(Get-WeekdayTextHash $doc.OuterXml)
    }
}
function Get-WeekdayFutureStart {
    param([string]$Clock,[ValidateSet('daily','weekly')][string]$Mode,[datetimeoffset]$Now=[datetimeoffset]::UtcNow)
    $zone=[TimeZoneInfo]::FindSystemTimeZoneById('Eastern Standard Time')
    $local=[TimeZoneInfo]::ConvertTime($Now,$zone).DateTime
    $candidate=$local.Date.Add([timespan]::ParseExact($Clock,'hh\:mm',[Globalization.CultureInfo]::InvariantCulture))
    while ($candidate -le $local -or ($Mode -eq 'weekly' -and $candidate.DayOfWeek -in @([DayOfWeek]::Saturday,[DayOfWeek]::Sunday))) { $candidate=$candidate.AddDays(1) }
    # Offset-free boundaries follow the verified Eastern Windows clock through DST.
    return $candidate.ToString('yyyy-MM-ddTHH:mm:ss',[Globalization.CultureInfo]::InvariantCulture)
}
function New-WeekdayTaskTrigger {
    param($Plan,[ValidateSet('daily','weekly')][string]$Mode)
    $at=[datetime]::ParseExact($Plan.Start.Substring(0,19),'yyyy-MM-ddTHH:mm:ss',[Globalization.CultureInfo]::InvariantCulture)
    if ($Mode -eq 'weekly') {
        $trigger=New-ScheduledTaskTrigger -Weekly -WeeksInterval 1 -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At $at
    } else { $trigger=New-ScheduledTaskTrigger -Daily -DaysInterval 1 -At $at }
    $trigger.StartBoundary=$Plan.Start;$trigger.Enabled=$Plan.Enabled
    if ($Plan.TriggerId) { $trigger.Id=$Plan.TriggerId }
    if ($Plan.ExecutionTimeLimit) { $trigger.ExecutionTimeLimit=$Plan.ExecutionTimeLimit }
    if ($Plan.RandomDelay) { $trigger.RandomDelay=$Plan.RandomDelay }
    return $trigger
}
function Assert-WeekdayTaskResult {
    param($Before,$After,[ValidateSet('daily','weekly')][string]$Mode,[string]$ExpectedStart=$Before.Start)
    $expected=@{Name=$Before.Name;Mode=$Mode;Start=$ExpectedStart;ProtectedHash=$Before.ProtectedHash;Enabled=$Before.Enabled;TriggerId=$Before.TriggerId;ExecutionTimeLimit=$Before.ExecutionTimeLimit;RandomDelay=$Before.RandomDelay}
    foreach ($property in $expected.Keys) {
        if ($After.$property -cne $expected[$property]) { throw ("Task readback differs at "+$property+"; preserve the receipt.") }
    }
}
function Assert-WeekdayTasksIdle {
    if (Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
        $_.Name -match '^python(w)?\.exe$' -and ([string]::IsNullOrWhiteSpace($_.CommandLine) -or $_.CommandLine -match 'bot\.py\b')
    }) { throw 'A bot command is running or cannot be inspected; retry after it finishes.' }
    foreach ($name in (Get-WeekdayTaskNames).Keys) {
        $task=Get-ScheduledTask -TaskName $name -TaskPath '\' -ErrorAction Stop
        if ($task.State -eq 'Running') { throw 'A bot task is running; no task was stopped.' }
    }
}
function Get-WeekdayFinancialState {
    param([string]$Repo,[string]$ToolRoot,[string]$Preserve)
    $python=Join-Path $Repo '.venv/Scripts/python.exe'
    $gateArgs=@('-B',(Join-Path $ToolRoot 'HOLDING-MAINTENANCE.py'),$Repo)
    if ($Preserve) { $gateArgs+=@('--preserve',$Preserve) }
    $output=& $python @gateArgs
    if ($LASTEXITCODE -ne 0) { throw ('Financial preservation gate refused: '+($output -join ' ')) }
    $value=($output -join "`n") | ConvertFrom-Json
    if ($value.ok -ne $true) { throw 'Financial preservation gate is incomplete.' }
    return $value
}
function Invoke-WeekdayTaskRepair {
    param([string]$Repo,[string]$ToolRoot,[switch]$Apply,[switch]$Rollback,[string]$Receipt)
    if ((Get-TimeZone).Id -ne 'Eastern Standard Time') { throw 'Windows must use Eastern Standard Time for the existing local bot cadence.' }
    if ($Rollback -and (!$Apply -or !$Receipt)) { throw 'Rollback requires -Apply and the printed -Receipt directory.' }
    $names=Get-WeekdayTaskNames
    $actual=@(Get-ScheduledTask -TaskPath '\' -TaskName 'CC bot *' -ErrorAction Stop | Select-Object -ExpandProperty TaskName)
    if ($actual.Count -ne 6 -or @(Compare-Object @($names.Keys) $actual).Count) { throw 'Expected exactly the six known root bot tasks.' }
    Assert-WeekdayTasksIdle
    $financial=Get-WeekdayFinancialState -Repo $Repo -ToolRoot $ToolRoot
    $originals=@{};$plans=@();$targets=@{};$starts=@{};$savedItems=@{};$rollbackStarts=@{};$readbacks=@{}
    if ($Rollback) {
        $Receipt=(Resolve-Path -LiteralPath $Receipt -ErrorAction Stop).Path
        $saved=Get-Content -LiteralPath (Join-Path $Receipt 'receipt.json') -Raw | ConvertFrom-Json
        if ($saved.version -ne 1 -or $saved.repo -ne $Repo -or $saved.tasks.Count -ne 6 -or
            @(Compare-Object @($names.Keys) @($saved.tasks.Name)).Count) { throw 'Receipt does not identify these six tasks and this repository.' }
        $progressPath=Join-Path $Receipt 'rollback-progress.json'
        if (Test-Path -LiteralPath $progressPath) {
            $progress=Get-Content -LiteralPath $progressPath -Raw | ConvertFrom-Json
            if ($progress.repo -ne $Repo -or $progress.version -ne 1) { throw 'Rollback progress is not for this repository.' }
            foreach ($entry in $progress.tasks) {
                if (!$names.Contains($entry.Name) -or $entry.Start -notmatch '^boundary=\d{4}-\d{2}-\d{2}T') { throw 'Invalid rollback progress.' }
                $rollbackStarts[$entry.Name]=$entry.Start.Substring(9)
            }
        }
        foreach ($item in $saved.tasks) {
            $xml=Get-Content -LiteralPath (Join-Path $Receipt ($item.Name+'.xml')) -Raw
            $original=Get-WeekdayTaskPlan -Xml $xml -Name $item.Name -Repo $Repo
            if ($original.XmlHash -ne $item.XmlHash) { throw 'Task backup checksum mismatch.' }
            if ($item.AppliedMode -notin @('daily','weekly') -or $item.AppliedStart -notmatch '^boundary=\d{4}-\d{2}-\d{2}T') { throw 'Receipt lacks a reviewed applied boundary.' }
            $originals[$item.Name]=$original;$savedItems[$item.Name]=$item
        }
    }
    foreach ($name in $names.Keys) {
        $xml=Export-ScheduledTask -TaskName $name -TaskPath '\' -ErrorAction Stop
        $plan=Get-WeekdayTaskPlan -Xml $xml -Name $name -Repo $Repo
        $plans+=,$plan;$readbacks[$name]=$plan
        if ($Rollback) {
            $target=$originals[$name]
            $record=$savedItems[$name]
            $expected=if ($plan.Mode -eq $record.AppliedMode) { $record.AppliedStart.Substring(9) } elseif ($plan.Mode -eq $target.Mode) { if ($rollbackStarts.ContainsKey($name)) { $rollbackStarts[$name] } else { $target.Start } } else { throw 'Unexpected current task schedule.' }
            Assert-WeekdayTaskResult -Before $target -After $plan -Mode $plan.Mode -ExpectedStart $expected
            $targets[$name]=$target.Mode
        } else { $targets[$name]='weekly' }
        $starts[$name]=if ($plan.Mode -ne $targets[$name]) { Get-WeekdayFutureStart -Clock $names[$name][2] -Mode $targets[$name] } else { $plan.Start }
    }
    $changes=@($plans | Where-Object { $_.Mode -ne $targets[$_.Name] })
    if (!$Apply -or !$changes.Count) {
        return [pscustomobject]@{ok=$true;applied=$false;pending_changes=$changes.Count;scope='SIX_BOT_TASK_TRIGGERS_ONLY';tasks=@($plans | Select-Object Name,Mode,Start);financial_state='verified; unchanged'}
    }
    $backup=Join-Path $Repo ('var/backups/weekday-tasks-'+(Get-Date -Format 'yyyyMMdd-HHmmss')+'-'+[guid]::NewGuid().ToString('N'))
    $lock=$null
    try {
        $lock=[IO.File]::Open((Join-Path $Repo 'var/monitor/holding-install.lock'),[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
        Assert-WeekdayTasksIdle
        New-Item -ItemType Directory -Path $backup -ErrorAction Stop | Out-Null
        foreach ($plan in $plans) { $plan.Xml | Set-Content -LiteralPath (Join-Path $backup ($plan.Name+'.xml')) -Encoding UTF8 }
        @{version=1;repo=$Repo;tasks=@($plans | ForEach-Object { @{Name=$_.Name;XmlHash=$_.XmlHash;AppliedMode=$targets[$_.Name];AppliedStart=('boundary='+$starts[$_.Name])} })} | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $backup 'receipt.json') -Encoding UTF8
        $preserve=Join-Path $backup 'financial-preservation.json'
        $financial | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $preserve -Encoding UTF8
        if ($Rollback) {
            $progressFile=Join-Path $Receipt 'rollback-progress.json'
            $progressTemp=Join-Path $Receipt ('rollback-progress-'+[guid]::NewGuid().ToString('N')+'.tmp')
            @{version=1;repo=$Repo;tasks=@($plans | ForEach-Object { @{Name=$_.Name;Start=('boundary='+$starts[$_.Name])} })} |
                ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $progressTemp -Encoding UTF8
            Move-Item -LiteralPath $progressTemp -Destination $progressFile -Force -ErrorAction Stop
        }
        Write-Host "Schedule recovery receipt: $backup"
        foreach ($plan in $changes) {
            Assert-WeekdayTasksIdle
            $current=Get-WeekdayTaskPlan -Xml (Export-ScheduledTask -TaskName $plan.Name -TaskPath '\' -ErrorAction Stop) -Name $plan.Name -Repo $Repo
            if ($current.XmlHash -ne $plan.XmlHash) { throw 'Task changed during preflight; preserve the receipt.' }
            $target=if ($Rollback) { $originals[$plan.Name] } else { $plan }
            $target=$target.PSObject.Copy();$target.Start=$starts[$plan.Name]
            $trigger=New-WeekdayTaskTrigger -Plan $target -Mode $targets[$plan.Name]
            Set-ScheduledTask -TaskName $plan.Name -TaskPath '\' -Trigger $trigger -ErrorAction Stop | Out-Null
            $after=Get-WeekdayTaskPlan -Xml (Export-ScheduledTask -TaskName $plan.Name -TaskPath '\' -ErrorAction Stop) -Name $plan.Name -Repo $Repo
            Assert-WeekdayTaskResult -Before $plan -After $after -Mode $targets[$plan.Name] -ExpectedStart $starts[$plan.Name]
            $readbacks[$plan.Name]=$after
        }
        Get-WeekdayFinancialState -Repo $Repo -ToolRoot $ToolRoot -Preserve $preserve | Out-Null
        return [pscustomobject]@{ok=$true;applied=$true;changed=$changes.Count;rollback=[bool]$Rollback;receipt=$backup;scope='SIX_BOT_TASK_TRIGGERS_ONLY';tasks=@($names.Keys | ForEach-Object { $readbacks[$_] } | Select-Object Name,Mode,Start,Enabled);financial_state='verified; unchanged'}
    } catch { throw ($_.Exception.Message+" Recovery receipt (if created): $backup. No task was started or stopped.") }
    finally { if ($lock) { $lock.Dispose() } }
}
