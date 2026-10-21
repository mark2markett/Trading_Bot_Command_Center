$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'SPY-SESSION-GUARDS.ps1')
$repo=Join-Path ([IO.Path]::GetTempPath()) ('spy-guard-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory (Join-Path $repo '.venv/Scripts') -Force | Out-Null
New-Item -ItemType Directory (Join-Path $repo 'bots/spy_mr_bot') -Force | Out-Null
New-Item -ItemType File (Join-Path $repo '.venv/Scripts/python.exe') | Out-Null
try {
 function Get-CimInstance {
  param($ClassName,$ErrorAction)
  switch($global:spyGuardCase){
   'spy_process' {return [pscustomobject]@{Name='python.exe';CommandLine='python.exe bot.py reconcile'}}
   'spy_path' {return [pscustomobject]@{Name='python.exe';CommandLine='python.exe C:\bots\spy_mr_bot\bot.py'}}
   'spy_module' {return [pscustomobject]@{Name='python.exe';CommandLine='python.exe -m bot decide'}}
   'unreadable' {return [pscustomobject]@{Name='python.exe';CommandLine=$null}}
   default {return [pscustomobject]@{Name='python.exe';CommandLine='python.exe bot.py session'}}
  }
 }
 function Get-ScheduledTask {
  param($TaskName,$TaskPath,$ErrorAction)
  $command=if($TaskName -like '* decide'){'decide'}else{'reconcile'}
  return [pscustomobject]@{State=$(if($global:spyGuardCase -eq 'running_task'){'Running'}else{'Ready'});Settings=@{Enabled=$true};Actions=@([pscustomobject]@{
   Execute=(Join-Path $repo '.venv/Scripts/python.exe');Arguments=$(if($global:spyGuardCase -eq 'wrong_action'){'bot.py session'}else{'bot.py '+$command});WorkingDirectory=(Join-Path $repo 'bots/spy_mr_bot')
  })}
 }
 function Get-ScheduledTaskInfo {
  param($InputObject,$ErrorAction)
  return [pscustomobject]@{NextRunTime=$(switch($global:spyGuardCase){'imminent'{(Get-Date).AddSeconds(60)} 'missing_time'{$null} 'stale_time'{(Get-Date).AddMinutes(-5)} default{(Get-Date).AddHours(3)}})}
 }
 foreach($scenario in @('intraday_sessions','spy_process','spy_path','spy_module','unreadable','running_task','imminent','missing_time','stale_time','wrong_action')){
  $global:spyGuardCase=$scenario;$failed=$false
  try {Assert-SpySessionIdle -Repo $repo} catch {$failed=$true}
  if(($scenario -eq 'intraday_sessions' -and $failed) -or ($scenario -ne 'intraday_sessions' -and !$failed)){throw ('Unexpected SPY guard result: '+$scenario)}
  Write-Host ($scenario+': passed')
 }
} finally {Remove-Item -LiteralPath $repo -Recurse -Force}
