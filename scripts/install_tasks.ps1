# Registers Windows Task Scheduler jobs for the Command Center. Run from the repo root in PowerShell:
#   powershell -ExecutionPolicy Bypass -File .\scripts\install_tasks.ps1
# Times are local; the trading PC should be on Eastern time.
$root = (Resolve-Path "$PSScriptRoot\..").Path
$py   = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = (Get-Command python).Source }
$set  = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -ExecutionTimeLimit (New-TimeSpan -Hours 20) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

# 1. Server: at logon, keep alive
$serverSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
$srvAct = New-ScheduledTaskAction -Execute $py -Argument "-m cc_server.main" -WorkingDirectory $root
$srvTrg = New-ScheduledTaskTrigger -AtLogOn
Register-ScheduledTask -TaskName "CC server" -Action $srvAct -Trigger $srvTrg -Settings $serverSettings -Force | Out-Null

# 2. Bots: one task per command per bot folder (skips _template_bot).
#    Daily bots (cadence decide/reconcile): 15:50 and 09:45.  Intraday bots (cadence "session"): one task at 09:25, 8 h limit.
$botSet = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
$sesSet = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -ExecutionTimeLimit (New-TimeSpan -Hours 8)
Get-ChildItem (Join-Path $root "bots") -Directory | Where-Object { $_.Name -notlike "_*" } | ForEach-Object {
  $bot = $_.FullName; $name = $_.Name
  $src = Get-Content (Join-Path $bot "bot.py") -Raw
  if ($src -match 'cadence=\{"session"') {
    $act = New-ScheduledTaskAction -Execute $py -Argument "bot.py session" -WorkingDirectory $bot
    $trg = New-ScheduledTaskTrigger -Daily -At "09:25"
    Register-ScheduledTask -TaskName "CC bot $name session" -Action $act -Trigger $trg -Settings $sesSet -Force | Out-Null
  } else {
    foreach ($pair in @(@("decide","15:50"), @("reconcile","09:45"))) {
      $cmd, $at = $pair
      $act = New-ScheduledTaskAction -Execute $py -Argument "bot.py $cmd" -WorkingDirectory $bot
      $trg = New-ScheduledTaskTrigger -Daily -At $at
      Register-ScheduledTask -TaskName "CC bot $name $cmd" -Action $act -Trigger $trg -Settings $botSet -Force | Out-Null
    }
  }
}

# 3. Nightly DB backup 23:30
$bkAct = New-ScheduledTaskAction -Execute $py -Argument "scripts\backup_db.py" -WorkingDirectory $root
$bkTrg = New-ScheduledTaskTrigger -Daily -At 23:30
Register-ScheduledTask -TaskName "CC backup" -Action $bkAct -Trigger $bkTrg -Settings $botSet -Force | Out-Null

Get-ScheduledTask -TaskName "CC *" | Select-Object TaskName, State
Write-Host "Installed. Early-close days: the server posts a reminder; run 'python bot.py decide' manually at 12:50 on those days (see README)."
