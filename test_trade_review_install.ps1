param([string]$Python='/workspace/.venv-readiness/bin/python')
$ErrorActionPreference='Stop'
$root=Join-Path ([IO.Path]::GetTempPath()) ('trade-review-wrapper-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory $root | Out-Null
try {
    foreach($scenario in @('success','busy','core_failure','old_api')){
        $package=Join-Path $root $scenario
        New-Item -ItemType Directory $package | Out-Null
        Copy-Item (Join-Path $PSScriptRoot 'INSTALL-TRADE-REVIEW.ps1') $package
        Copy-Item (Join-Path $PSScriptRoot 'TRADE-REVIEW-GUARDS.ps1') $package
        @'
param([string]$Repo)
$global:reviewCoreInvoked=$true
if($global:reviewScenario -eq 'core_failure'){throw 'Simulated core installation failure'}
$global:LASTEXITCODE=0
'@ | Set-Content (Join-Path $package 'REPAIR-OPERATIONS.ps1')
        @('TRADE-REVIEW-GUARDS.ps1','REPAIR-OPERATIONS.ps1') | ForEach-Object {
            (Get-FileHash (Join-Path $package $_)).Hash.ToLower()+'  '+$_
        } | Set-Content (Join-Path $package 'TRADE-REVIEW-SHA256.txt')
        $global:reviewCoreInvoked=$false;$global:reviewScenario=$scenario
        function Get-CimInstance {
            param($ClassName,$ErrorAction)
            if($global:reviewScenario -eq 'busy'){return [pscustomobject]@{Name='python.exe';CommandLine='python.exe bot.py session'}}
            return @()
        }
        function Get-ScheduledTask {param($TaskName,$ErrorAction) return @()}
        function Invoke-RestMethod {
            param($Uri,$TimeoutSec)
            if(!$global:reviewCoreInvoked){throw 'API queried before installation'}
            if($Uri -like '*/reviews'){return [pscustomobject]@{worker=@{status='written'}}}
            if($global:reviewScenario -eq 'old_api'){return [pscustomobject]@{}}
            return [pscustomobject]@{schema_version=1;execution=@{broker_verified=$false};session_date='2026-10-20';summary=@{observed_candidates=0;closed_trades=0}}
        }
        $failed=$false
        try { & (Join-Path $package 'INSTALL-TRADE-REVIEW.ps1') -Repo $package } catch {$failed=$true}
        if($scenario -eq 'success' -and ($failed -or !$global:reviewCoreInvoked)){throw 'Review wrapper did not complete'}
        if($scenario -ne 'success' -and !$failed){throw 'Review wrapper accepted failed verification'}
        if($scenario -eq 'busy' -and $global:reviewCoreInvoked){throw 'Busy wrapper invoked mutation helper'}
        Write-Host ($scenario+': passed')
    }
} finally { Remove-Item -LiteralPath $root -Recurse -Force }
