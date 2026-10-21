param([string]$Python='/workspace/.venv-readiness/bin/python')
$ErrorActionPreference='Stop'
$root=Join-Path ([IO.Path]::GetTempPath()) ('paper-exit-wrapper-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory $root | Out-Null
try {
    foreach($scenario in @('success','busy','core_failure','busy_after_install','apply_failure','verify_failure')) {
        $package=Join-Path $root $scenario
        $repo=Join-Path $package 'repo'
        New-Item -ItemType Directory (Join-Path $repo 'var/monitor') -Force | Out-Null
        New-Item -ItemType Directory (Join-Path $repo '.venv/Scripts') -Force | Out-Null
        New-Item -ItemType Directory (Join-Path $repo 'var/backups') -Force | Out-Null
        Copy-Item (Join-Path $PSScriptRoot 'REPAIR-PAPER-EXIT-STATE.ps1') $package
        Copy-Item (Join-Path $PSScriptRoot 'TRADE-REVIEW-GUARDS.ps1') $package
        @'
param([string]$Repo)
$global:paperSourceInstalled=$true
if($global:paperScenario -eq 'core_failure'){throw 'Simulated installation failure'}
$global:LASTEXITCODE=0
'@ | Set-Content (Join-Path $package 'INSTALL-TRADE-REVIEW.ps1')
        'test helper placeholder' | Set-Content (Join-Path $package 'PAPER-EXIT-STATE.py')
        @('TRADE-REVIEW-GUARDS.ps1','INSTALL-TRADE-REVIEW.ps1','PAPER-EXIT-STATE.py') | ForEach-Object {
            (Get-FileHash (Join-Path $package $_)).Hash.ToLower()+'  '+$_
        } | Set-Content (Join-Path $package 'PAPER-EXIT-SHA256.txt')
        $global:paperSourceInstalled=$false;$global:paperScenario=$scenario;$global:paperActions=@()
        $pythonPath=Join-Path $repo '.venv/Scripts/python.exe'
        # PowerShell resolves a function with this exact path before an external executable.
        Set-Item -Path ('Function:global:'+$pythonPath) -Value {
            $action=$args[2]
            if(!$global:paperSourceInstalled){throw 'Mutation helper ran before source installation'}
            $global:paperActions+=@($action)
            $global:LASTEXITCODE=if(($action -eq 'apply' -and $global:paperScenario -eq 'apply_failure') -or ($action -eq 'verify' -and $global:paperScenario -eq 'verify_failure')){1}else{0}
            '{"ok":true}'
        }
        function Get-CimInstance {
            param($ClassName,$ErrorAction)
            if($global:paperScenario -eq 'busy' -or ($global:paperSourceInstalled -and $global:paperScenario -eq 'busy_after_install')){
                return [pscustomobject]@{Name='python.exe';CommandLine='python.exe bot.py reconcile'}
            }
            return @()
        }
        function Get-ScheduledTask {param($TaskName,$ErrorAction) return @()}
        $failed=$false
        try { & (Join-Path $package 'REPAIR-PAPER-EXIT-STATE.ps1') -Repo $repo } catch {$failed=$true}
        if($scenario -eq 'success' -and ($failed -or ($global:paperActions -join ',') -ne 'prepare,apply,verify')){throw 'Metadata wrapper did not complete in order'}
        if($scenario -ne 'success' -and !$failed){throw 'Metadata wrapper accepted a failure'}
        if($scenario -eq 'busy' -and $global:paperSourceInstalled){throw 'Busy wrapper installed source'}
        if($scenario -in @('busy','core_failure','busy_after_install') -and $global:paperActions.Count){throw 'Unsafe wrapper invoked metadata helper'}
        $stream=[IO.File]::Open((Join-Path $repo 'var/monitor/holding-install.lock'),[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
        $stream.Dispose()
        Remove-Item -LiteralPath ('Function:global:'+$pythonPath)
        Write-Host ($scenario+': passed')
    }
} finally { Remove-Item -LiteralPath $root -Recurse -Force }
