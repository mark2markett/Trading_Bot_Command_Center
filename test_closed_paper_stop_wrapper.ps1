param([string]$Python='/workspace/.venv-readiness/bin/python')
$ErrorActionPreference='Stop'
$root=Join-Path ([IO.Path]::GetTempPath()) ('paper-exit-wrapper-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory $root | Out-Null
try {
    foreach($scenario in @('success','busy','busy_after_prepare','apply_failure','verify_failure')) {
        $package=Join-Path $root $scenario
        $repo=Join-Path $package 'repo'
        New-Item -ItemType Directory (Join-Path $repo 'var/monitor') -Force | Out-Null
        New-Item -ItemType Directory (Join-Path $repo '.venv/Scripts') -Force | Out-Null
        New-Item -ItemType Directory (Join-Path $repo 'var/backups') -Force | Out-Null
        Copy-Item (Join-Path $PSScriptRoot 'RECONCILE-CLOSED-PAPER-STOP.ps1') $package
        Copy-Item (Join-Path $PSScriptRoot 'SPY-SESSION-GUARDS.ps1') $package
        @'
function Assert-SpySessionIdle {
    param($Repo)
    if($global:paperScenario -eq 'busy' -or ($global:paperScenario -eq 'busy_after_prepare' -and $global:paperActions.Count)){throw 'SPY is busy'}
}
'@ | Set-Content (Join-Path $package 'SPY-SESSION-GUARDS.ps1')
        'test helper placeholder' | Set-Content (Join-Path $package 'PAPER-EXIT-STATE.py')
        @('SPY-SESSION-GUARDS.ps1','PAPER-EXIT-STATE.py') | ForEach-Object {
            (Get-FileHash (Join-Path $package $_)).Hash.ToLower()+'  '+$_
        } | Set-Content (Join-Path $package 'CLOSED-PAPER-STOP-SHA256.txt')
        $global:paperSourceInstalled=$false;$global:paperScenario=$scenario;$global:paperActions=@()
        $pythonPath=Join-Path $repo '.venv/Scripts/python.exe'
        # PowerShell resolves a function with this exact path before an external executable.
        Set-Item -Path ('Function:global:'+$pythonPath) -Value {
            $action=$args[2]
            $global:paperActions+=@($action)
            $global:LASTEXITCODE=if(($action -eq 'apply' -and $global:paperScenario -eq 'apply_failure') -or ($action -eq 'verify' -and $global:paperScenario -eq 'verify_failure')){1}else{0}
            '{"ok":true}'
        }
        $failed=$false
        try { & (Join-Path $package 'RECONCILE-CLOSED-PAPER-STOP.ps1') -Repo $repo } catch {$failed=$true}
        if($scenario -eq 'success' -and ($failed -or ($global:paperActions -join ',') -ne 'prepare,apply,verify')){throw 'Metadata wrapper did not complete in order'}
        if($scenario -ne 'success' -and !$failed){throw 'Metadata wrapper accepted a failure'}
        if($scenario -eq 'busy' -and $global:paperActions.Count){throw 'Busy wrapper invoked mutation helper'}
        if($scenario -eq 'busy_after_prepare' -and ($global:paperActions -join ',') -ne 'prepare'){throw 'SPY idle not rechecked before mutation'}
        $stream=[IO.File]::Open((Join-Path $repo 'var/monitor/holding-install.lock'),[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
        $stream.Dispose()
        Remove-Item -LiteralPath ('Function:global:'+$pythonPath)
        Write-Host ($scenario+': passed')
    }
} finally { Remove-Item -LiteralPath $root -Recurse -Force }
