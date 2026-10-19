[CmdletBinding()]
param(
    [string]$Repo='C:\Users\Administrator\trading_bots\command-center',
    [Parameter(Mandatory=$true)][string]$Receipt
)
$ErrorActionPreference='Stop'
if ($env:OS -ne 'Windows_NT') { throw 'This read-only check requires Windows Task Scheduler.' }
$Repo=(Resolve-Path -LiteralPath $Repo -ErrorAction Stop).Path
$Receipt=(Resolve-Path -LiteralPath $Receipt -ErrorAction Stop).Path
foreach ($name in @('CC bot gap_go_bot session','CC bot gap_go_spread_bot session')) {
    $old=[xml](Get-Content -LiteralPath (Join-Path $Receipt ($name+'.xml')) -Raw)
    $new=[xml](Export-ScheduledTask -TaskName $name -TaskPath '\' -ErrorAction Stop)
    $task=Get-ScheduledTask -TaskName $name -TaskPath '\' -ErrorAction Stop
    [pscustomobject]@{
        Task=$name;Trigger=$task.Triggers[0].CimClass.CimClassName
        OriginalTriggerLimit=[string]$old.Task.Triggers.CalendarTrigger.ExecutionTimeLimit
        CurrentTriggerLimit=[string]$new.Task.Triggers.CalendarTrigger.ExecutionTimeLimit
        NativeTriggerLimit=$task.Triggers[0].ExecutionTimeLimit
        OriginalTaskLimit=[string]$old.Task.Settings.ExecutionTimeLimit
        CurrentTaskLimit=[string]$new.Task.Settings.ExecutionTimeLimit
        ActionsPreserved=($old.Task.Actions.OuterXml -ceq $new.Task.Actions.OuterXml)
        PrincipalPreserved=($old.Task.Principals.OuterXml -ceq $new.Task.Principals.OuterXml)
        SettingsPreserved=($old.Task.Settings.OuterXml -ceq $new.Task.Settings.OuterXml)
        CurrentStart=$task.Triggers[0].StartBoundary
    } | Format-List
}
