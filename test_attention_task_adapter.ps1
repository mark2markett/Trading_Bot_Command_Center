param([string]$NativeRepo='/workspace/scratch/cc-dashboard-wrap-20261007')
$ErrorActionPreference='Stop'
$root=Join-Path ([IO.Path]::GetTempPath()) ('attention-task-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path (Join-Path $root '.venv\Scripts') -Force | Out-Null
$python=Join-Path $root '.venv\Scripts\python.exe'; New-Item -ItemType File -Path $python | Out-Null
$global:attentionStarts=0; $global:attentionProcesses=@(); $global:attentionListener=$false
$global:attentionTask=[pscustomobject]@{Actions=@([pscustomobject]@{Execute=$python;Arguments='-m cc_server.main';WorkingDirectory=$root});Settings=[pscustomobject]@{Enabled=$true};State='Ready'}
function Get-ScheduledTask { param($TaskName,$ErrorAction) return $global:attentionTask }
function Get-CimInstance { param($ClassName,$ErrorAction) return $global:attentionProcesses }
function Get-NetTCPConnection { param($LocalPort,$State,$ErrorAction) if ($global:attentionListener) { return [pscustomobject]@{LocalPort=8585} } }
function Start-ScheduledTask { param($TaskName,$ErrorAction) $global:attentionStarts++ }
try {
    $adapter=Join-Path $NativeRepo 'scripts/incident_task.ps1'
    & $adapter -Repo $root -Action Start | Out-Null
    if ($global:attentionStarts -ne 1) { throw 'Owned stopped task should start exactly once.' }
    $global:attentionProcesses=@([pscustomobject]@{Name='python.exe';CommandLine='python.exe -m cc_server.main'})
    $refused=$false
    try { & $adapter -Repo $root -Action Start | Out-Null } catch { $refused=$true }
    if (!$refused -or $global:attentionStarts -ne 1) { throw 'Inspectable manual server must prevent duplicate server start.' }
    $global:attentionProcesses=@(); $global:attentionListener=$true
    $refused=$false
    try { & $adapter -Repo $root -Action Start | Out-Null } catch { $refused=$true }
    if (!$refused -or $global:attentionStarts -ne 1) { throw 'Existing listener must prevent duplicate server start.' }
    Write-Host '3 server task adapter scenarios passed.'
} finally {
    Remove-Item -LiteralPath $root -Recurse -Force
    Remove-Variable attentionStarts,attentionProcesses,attentionListener,attentionTask -Scope Global
}
