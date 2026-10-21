$ErrorActionPreference='Stop'
$root=Join-Path ([IO.Path]::GetTempPath()) ('spy-source-wrapper-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory $root | Out-Null
try {
 foreach($scenario in @('success','busy','busy_after_prepare','prepare_failure','apply_failure')){
  $package=Join-Path $root $scenario;$repo=Join-Path $package 'repo'
  New-Item -ItemType Directory (Join-Path $repo 'var/monitor') -Force | Out-Null
  New-Item -ItemType Directory (Join-Path $repo '.venv/Scripts') -Force | Out-Null
  New-Item -ItemType Directory (Join-Path $repo 'var/backups') -Force | Out-Null
  Copy-Item (Join-Path $PSScriptRoot 'INSTALL-SPY-SESSION-GUARD.ps1') $package
  @'
function Assert-SpySessionIdle {
 param($Repo)
 if($global:spyWrapperCase -eq 'busy' -or ($global:spyWrapperCase -eq 'busy_after_prepare' -and $global:spyWrapperActions.Count)){throw 'SPY is busy'}
}
'@ | Set-Content (Join-Path $package 'SPY-SESSION-GUARDS.ps1')
  'test helper placeholder' | Set-Content (Join-Path $package 'SPY-SESSION-INSTALL.py')
  @('SPY-SESSION-GUARDS.ps1','SPY-SESSION-INSTALL.py') | ForEach-Object {(Get-FileHash (Join-Path $package $_)).Hash.ToLower()+'  '+$_} | Set-Content (Join-Path $package 'SPY-SESSION-SHA256.txt')
  $global:spyWrapperCase=$scenario;$global:spyWrapperActions=@()
  $python=Join-Path $repo '.venv/Scripts/python.exe'
  Set-Item -Path ('Function:global:'+$python) -Value {
   $action=$args[2];$global:spyWrapperActions+=@($action)
   $global:LASTEXITCODE=if(($action -eq 'prepare' -and $global:spyWrapperCase -eq 'prepare_failure') -or ($action -eq 'apply' -and $global:spyWrapperCase -eq 'apply_failure')){1}else{0}
   @{ok=$true;receipt=(Join-Path $repo 'var/backups/spy-session-test.json')} | ConvertTo-Json -Compress
  }
  $failed=$false
  try {& (Join-Path $package 'INSTALL-SPY-SESSION-GUARD.ps1') -Repo $repo} catch {$failed=$true}
  if($scenario -eq 'success' -and ($failed -or ($global:spyWrapperActions -join ',') -ne 'prepare,apply,verify')){throw 'SPY wrapper did not complete'}
  if($scenario -ne 'success' -and !$failed){throw 'SPY wrapper accepted a failure'}
  if($scenario -eq 'busy' -and $global:spyWrapperActions.Count){throw 'Busy wrapper invoked helper'}
  if($scenario -eq 'busy_after_prepare' -and ($global:spyWrapperActions -join ',') -ne 'prepare'){throw 'SPY guard was not rechecked before apply'}
  $stream=[IO.File]::Open((Join-Path $repo 'var/monitor/holding-install.lock'),[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None);$stream.Dispose()
  Remove-Item -LiteralPath ('Function:global:'+$python)
  Write-Host ($scenario+': passed')
 }
} finally {Remove-Item -LiteralPath $root -Recurse -Force}
