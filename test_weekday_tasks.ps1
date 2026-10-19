$ErrorActionPreference='Stop'
$helper=Join-Path $PSScriptRoot 'WEEKDAY-TASK-HELPERS.ps1'
if (!(Test-Path -LiteralPath $helper)) { throw 'No guarded weekday-task repair exists.' }
. $helper
$root=Join-Path ([IO.Path]::GetTempPath()) ('weekday-tests-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $root | Out-Null
try {
    $Repo=$root;$python=Join-Path $Repo '.venv/Scripts/python.exe'
    New-Item -ItemType Directory -Path (Split-Path $python) -Force | Out-Null
    New-Item -ItemType File -Path $python | Out-Null
    $folder=Join-Path $Repo 'bots/spy_mr_bot'
    New-Item -ItemType Directory -Path $folder -Force | Out-Null
    $escape=[System.Security.SecurityElement]
    $xml='<Task xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task"><RegistrationInfo><URI>\CC bot spy_mr_bot reconcile</URI></RegistrationInfo><Triggers><CalendarTrigger id="owned"><StartBoundary>2026-10-03T09:45:00-04:00</StartBoundary><Enabled>true</Enabled><ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay></CalendarTrigger></Triggers><Principals><Principal id="Author"><UserId>owner</UserId><LogonType>InteractiveToken</LogonType></Principal></Principals><Settings><Enabled>true</Enabled><StartWhenAvailable>true</StartWhenAvailable></Settings><Actions Context="Author"><Exec><Command>'+[System.Security.SecurityElement]::Escape($python)+'</Command><Arguments>bot.py reconcile</Arguments><WorkingDirectory>'+[System.Security.SecurityElement]::Escape($folder)+'</WorkingDirectory></Exec></Actions></Task>'
    $plan=Get-WeekdayTaskPlan -Xml $xml -Name 'CC bot spy_mr_bot reconcile' -Repo $Repo
    if ($plan.Mode -ne 'daily' -or $plan.Start -ne '2026-10-03T09:45:00-04:00') { throw 'Daily task plan was not preserved.' }
    $script:parameters=$null
    function New-ScheduledTaskTrigger {
        param([switch]$Weekly,[switch]$Daily,$WeeksInterval,$DaysOfWeek,$DaysInterval,$At)
        $script:parameters=@{}+$PSBoundParameters
        return [pscustomobject]@{StartBoundary='';Enabled=$true;Id='';ExecutionTimeLimit='';RandomDelay=''}
    }
    $trigger=New-WeekdayTaskTrigger -Plan $plan -Mode weekly
    if (!$script:parameters.Weekly -or $script:parameters.WeeksInterval -ne 1 -or ($script:parameters.DaysOfWeek -join ',') -ne 'Monday,Tuesday,Wednesday,Thursday,Friday') { throw 'Weekend exclusions are missing.' }
    if ($trigger.StartBoundary -ne $plan.Start -or $trigger.Id -ne 'owned') { throw 'Original trigger time or identity changed.' }
    $weekly=$xml.Replace('<ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>','<ScheduleByWeek><WeeksInterval>1</WeeksInterval><DaysOfWeek><Monday/><Tuesday/><Wednesday/><Thursday/><Friday/></DaysOfWeek></ScheduleByWeek>')
    $installed=Get-WeekdayTaskPlan -Xml $weekly -Name $plan.Name -Repo $Repo
    Assert-WeekdayTaskResult -Before $plan -After $installed -Mode weekly
    New-WeekdayTaskTrigger -Plan $plan -Mode daily | Out-Null
    if (!$script:parameters.Daily -or $script:parameters.DaysInterval -ne 1) { throw 'Daily rollback does not restore the original interval.' }
    $checks=4
    foreach ($bad in @(
        $xml.Replace('bot.py reconcile','bot.py reconcile -Command bad'),
        $xml.Replace('spy_mr_bot</WorkingDirectory>','other</WorkingDirectory>'),
        $xml.Replace('<DaysInterval>1</DaysInterval>','<DaysInterval>2</DaysInterval>'),
        $weekly.Replace('<Friday/>','<Friday/><Sunday/>'),
        $xml.Replace('09:45:00','10:45:00'),
        $xml.Replace('<Enabled>true</Enabled><ScheduleByDay>','<Enabled>true</Enabled><Repetition><Interval>PT1M</Interval></Repetition><ScheduleByDay>')
    )) {
        $refused=$false;try { Get-WeekdayTaskPlan -Xml $bad -Name $plan.Name -Repo $Repo | Out-Null } catch { $refused=$true }
        if (!$refused) { throw 'An unexpected task definition was accepted.' };$checks++
    }
    $changed=Get-WeekdayTaskPlan -Xml ($weekly.Replace('<StartWhenAvailable>true','<StartWhenAvailable>false')) -Name $plan.Name -Repo $Repo
    $refused=$false;try { Assert-WeekdayTaskResult -Before $plan -After $changed -Mode weekly } catch { $refused=$true }
    if (!$refused) { throw 'Task settings changed without detection.' };$checks++
    if ((Get-WeekdayTaskNames).Count -ne 6) { throw 'Repair must target exactly six bot commands.' };$checks++

    $future=Get-WeekdayFutureStart -Clock '09:45' -Mode weekly -Now ([datetimeoffset]'2026-10-18T23:30:00-04:00')
    if($future -ne '2026-10-19T09:45:00') { throw 'Weekend catch-up was not prevented.' };$checks++
    $future=Get-WeekdayFutureStart -Clock '09:25' -Mode weekly -Now ([datetimeoffset]'2026-10-31T23:30:00-04:00')
    if($future -ne '2026-11-02T09:25:00') { throw 'Future boundary does not preserve Eastern clock through DST.' };$checks++
    $future=Get-WeekdayFutureStart -Clock '09:45' -Mode daily -Now ([datetimeoffset]'2026-10-16T23:30:00-04:00')
    if($future -ne '2026-10-17T09:45:00') { throw 'Rollback boundary can catch up an obsolete daily occurrence.' };$checks++

    # Exercise the real repair flow with an isolated Task Scheduler adapter.
    New-Item -ItemType Directory -Path (Join-Path $Repo 'var/monitor') -Force | Out-Null
    $script:definitions=@{};$script:setCount=0;$script:running=$false;$script:badProcess=$false;$script:zone='Eastern Standard Time';$script:failAt=0
    foreach ($name in (Get-WeekdayTaskNames).Keys) {
        $spec=(Get-WeekdayTaskNames)[$name]
        $directory=Join-Path $Repo ('bots/'+$spec[0]);New-Item -ItemType Directory -Path $directory -Force | Out-Null
        $text=$xml.Replace('CC bot spy_mr_bot reconcile',$name).Replace([Security.SecurityElement]::Escape($folder),[Security.SecurityElement]::Escape($directory)).Replace('bot.py reconcile','bot.py '+$spec[1]).Replace('09:45:00',$spec[2]+':00')
        $script:definitions[$name]=$text
    }
    function Get-TimeZone { [pscustomobject]@{Id=$script:zone} }
    function Get-CimInstance {
        param($ClassName,$ErrorAction)
        if ($script:badProcess) { return [pscustomobject]@{Name='python.exe';CommandLine=''} };return @()
    }
    function Get-ScheduledTask {
        param($TaskName,$TaskPath,$ErrorAction)
        foreach ($name in $script:definitions.Keys) {
            if ($name -like $TaskName) { [pscustomobject]@{TaskName=$name;State=$(if($script:running){'Running'}else{'Ready'})} }
        }
    }
    function Export-ScheduledTask { param($TaskName,$TaskPath,$ErrorAction) return $script:definitions[$TaskName] }
    function New-ScheduledTaskTrigger {
        param([switch]$Weekly,[switch]$Daily,$WeeksInterval,$DaysOfWeek,$DaysInterval,$At)
        return [pscustomobject]@{Mode=$(if($Weekly){'weekly'}else{'daily'});StartBoundary='';Enabled=$true;Id='';ExecutionTimeLimit='';RandomDelay=''}
    }
    function Set-ScheduledTask {
        param($TaskName,$TaskPath,$Trigger,$ErrorAction)
        $script:setCount++
        if($script:failAt -eq $script:setCount) { throw 'Isolated scheduled-task update failure.' }
        $doc=[xml]$script:definitions[$TaskName];$ns=New-Object Xml.XmlNamespaceManager($doc.NameTable);$ns.AddNamespace('t',$doc.DocumentElement.NamespaceURI)
        $calendar=$doc.SelectSingleNode('/t:Task/t:Triggers/t:CalendarTrigger',$ns)
        $calendar.SelectSingleNode('t:StartBoundary',$ns).InnerText=$Trigger.StartBoundary
        $calendar.SelectSingleNode('t:Enabled',$ns).InnerText=([string]$Trigger.Enabled).ToLowerInvariant()
        if($Trigger.Id) { $calendar.SetAttribute('id',$Trigger.Id) } else { $calendar.RemoveAttribute('id') }
        foreach($property in @('ExecutionTimeLimit','RandomDelay')) {
            $node=$calendar.SelectSingleNode('t:'+$property,$ns)
            if(!$node) { $node=$doc.CreateElement($property,$doc.DocumentElement.NamespaceURI);$calendar.AppendChild($node) | Out-Null }
            $node.InnerText=if($Trigger.$property){$Trigger.$property}elseif($property -eq 'RandomDelay'){'PT0S'}else{'PT72H'}
        }

        $old=$calendar.SelectSingleNode('t:ScheduleByDay|t:ScheduleByWeek',$ns);$calendar.RemoveChild($old) | Out-Null
        $kind=if($Trigger.Mode -eq 'weekly'){'ScheduleByWeek'}else{'ScheduleByDay'}
        $schedule=$doc.CreateElement($kind,$doc.DocumentElement.NamespaceURI)
        if($Trigger.Mode -eq 'weekly') { $schedule.InnerXml='<WeeksInterval xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">1</WeeksInterval><DaysOfWeek xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task"><Monday/><Tuesday/><Wednesday/><Thursday/><Friday/></DaysOfWeek>' }
        else { $schedule.InnerXml='<DaysInterval xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">1</DaysInterval>' }
        $calendar.AppendChild($schedule) | Out-Null
        $script:definitions[$TaskName]=$doc.OuterXml
    }
    function Get-WeekdayFinancialState {
        param($Repo,$ToolRoot,$Preserve)
        if($Preserve -and !(Test-Path -LiteralPath $Preserve)) { throw 'No pre-change financial receipt.' }
        return [pscustomobject]@{ok=$true;fingerprint='isolated fixture';history=@{}}
    }
    $report=Invoke-WeekdayTaskRepair -Repo $Repo -ToolRoot $PSScriptRoot
    if($report.pending_changes -ne 6 -or $script:setCount -ne 0) { throw 'Read-only mode mutated tasks or missed a daily trigger.' };$checks++
    $report=Invoke-WeekdayTaskRepair -Repo $Repo -ToolRoot $PSScriptRoot -Apply
    if(!$report.ok -or $report.changed -ne 6 -or $script:setCount -ne 6) { throw 'Six-task repair failed.' };$checks++
    if($report.tasks.Count -ne 6 -or @($report.tasks | Where-Object { $_.Mode -ne 'weekly' -or $_.Start -match '(?:Z|[+-]\d{2}:\d{2})$' }).Count) { throw 'Verified schedule is not six Eastern local weekday triggers.' };$checks++
    $receipt=$report.receipt
    $report=Invoke-WeekdayTaskRepair -Repo $Repo -ToolRoot $PSScriptRoot -Apply
    if($report.applied -or $report.pending_changes -ne 0 -or $script:setCount -ne 6) { throw 'Repeated application was not idempotent.' };$checks++
    $report=Invoke-WeekdayTaskRepair -Repo $Repo -ToolRoot $PSScriptRoot -Apply -Rollback -Receipt $receipt
    if(!$report.ok -or $report.changed -ne 6 -or $script:setCount -ne 12) { throw 'Trigger-only rollback failed.' };$checks++
    $report=Invoke-WeekdayTaskRepair -Repo $Repo -ToolRoot $PSScriptRoot -Apply -Rollback -Receipt $receipt
    if($report.applied -or $script:setCount -ne 12) { throw 'Repeated rollback must preserve the completed future schedule.' };$checks++
    $again=Invoke-WeekdayTaskRepair -Repo $Repo -ToolRoot $PSScriptRoot -Apply
    $script:failAt=20;$refused=$false
    try { Invoke-WeekdayTaskRepair -Repo $Repo -ToolRoot $PSScriptRoot -Apply -Rollback -Receipt $again.receipt | Out-Null } catch { $refused=$true }
    if(!$refused -or $script:setCount -ne 20) { throw 'Partial rollback fixture did not fail after one restored task.' }
    $script:failAt=0
    $report=Invoke-WeekdayTaskRepair -Repo $Repo -ToolRoot $PSScriptRoot -Apply -Rollback -Receipt $again.receipt
    if(!$report.ok -or $report.changed -ne 5 -or $script:setCount -ne 25) { throw 'Same-receipt retry could not complete a partial rollback.' };$checks++
    $report=Invoke-WeekdayTaskRepair -Repo $Repo -ToolRoot $PSScriptRoot -Apply -Rollback -Receipt $again.receipt
    if($report.applied -or $script:setCount -ne 25) { throw 'Completed partial rollback cannot be repeated safely.' };$checks++
    $baselineSetCount=$script:setCount
    foreach($fault in @('running','process','timezone','ownership')) {
        $script:running=($fault -eq 'running');$script:badProcess=($fault -eq 'process');$script:zone=if($fault -eq 'timezone'){'UTC'}else{'Eastern Standard Time'}
        $name='CC bot spy_mr_bot reconcile';$saved=$script:definitions[$name]
        if($fault -eq 'ownership') { $script:definitions[$name]=$saved.Replace('bot.py reconcile','bot.py reconcile -Command bad') }
        $refused=$false;try { Invoke-WeekdayTaskRepair -Repo $Repo -ToolRoot $PSScriptRoot -Apply | Out-Null } catch {$refused=$true}
        $script:definitions[$name]=$saved
        if(!$refused -or $script:setCount -ne $baselineSetCount) { throw 'Unsafe repair preflight changed a task.' };$checks++
    }

    Write-Host "$checks weekday schedule ownership, timing, preservation and rollback checks passed."
} finally { Remove-Item -LiteralPath $root -Recurse -Force }
