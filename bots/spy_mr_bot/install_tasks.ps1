# Run once in PowerShell (as your user) from the bot folder. Creates two daily Windows tasks.
# Times are local to this PC; adjust if the PC is not on Eastern time.
$py   = (Get-Command python).Source
$here = $PSScriptRoot
$act1 = New-ScheduledTaskAction -Execute $py -Argument "bot.py decide"    -WorkingDirectory $here
$act2 = New-ScheduledTaskAction -Execute $py -Argument "bot.py reconcile" -WorkingDirectory $here
$trg1 = New-ScheduledTaskTrigger -Daily -At 15:50
$trg2 = New-ScheduledTaskTrigger -Daily -At 09:45
$set  = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
Register-ScheduledTask -TaskName "SPY-MR decide"    -Action $act1 -Trigger $trg1 -Settings $set -Force
Register-ScheduledTask -TaskName "SPY-MR reconcile" -Action $act2 -Trigger $trg2 -Settings $set -Force
Write-Host "Tasks installed. Check them in Task Scheduler > Task Scheduler Library."
