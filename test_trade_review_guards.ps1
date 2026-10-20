$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'TRADE-REVIEW-GUARDS.ps1')
$global:reviewGuardScenario='idle'
function Get-CimInstance {
    param($ClassName,$ErrorAction)
    switch($global:reviewGuardScenario){
        'running_bot' { return [pscustomobject]@{Name='python.exe';CommandLine='python.exe bot.py session'} }
        'unreadable' { return [pscustomobject]@{Name='python.exe';CommandLine=$null} }
        default { return [pscustomobject]@{Name='python.exe';CommandLine='python.exe -m cc_server.main'} }
    }
}
function Get-ScheduledTask {
    param($TaskName,$ErrorAction)
    if($TaskName -ne 'CC bot *'){throw 'Unexpected task inspection'}
    return [pscustomobject]@{TaskName='CC bot spy_mr_bot decide';State=$(if($global:reviewGuardScenario -eq 'running_task'){'Running'}else{'Ready'})}
}
function Get-ScheduledTaskInfo {
    param($InputObject,$ErrorAction)
    return [pscustomobject]@{NextRunTime=$(if($global:reviewGuardScenario -eq 'imminent'){(Get-Date).AddSeconds(100)}else{(Get-Date).AddHours(3)})}
}
foreach($scenario in @('idle','running_bot','unreadable','running_task','imminent')){
    $global:reviewGuardScenario=$scenario;$failed=$false
    try { Assert-TradeReviewIdle } catch { $failed=$true }
    if(($scenario -eq 'idle' -and $failed) -or ($scenario -ne 'idle' -and !$failed)){throw ('Unexpected guard result: '+$scenario)}
}
Write-Host 'PASS: idle, running bot/task, unreadable process and imminent task guards.'
