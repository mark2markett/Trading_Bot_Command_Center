param([string]$Repo='C:\Users\Administrator\trading_bots\command-center',[switch]$Activate,[switch]$Rollback,[string]$Receipt)
$ErrorActionPreference='Stop'
$Repo=(Resolve-Path -LiteralPath $Repo).Path
$python=Join-Path $Repo '.venv\Scripts\python.exe'
$runtime=Join-Path $Repo 'var'
$power=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
foreach ($line in Get-Content -LiteralPath (Join-Path $PSScriptRoot 'HOLDING-MAINTENANCE-SHA256.txt')) {
    if ($line -notmatch '^([a-f0-9]{64})\s+([A-Za-z0-9_.-]+)$') { throw 'Invalid maintenance checksum entry.' }
    if ((Get-FileHash -LiteralPath (Join-Path $PSScriptRoot $Matches[2])).Hash -ne $Matches[1]) { throw 'Maintenance checksum mismatch.' }
}
. (Join-Path $PSScriptRoot 'ATTENTION-TASK-OWNERSHIP.ps1')
. (Join-Path $PSScriptRoot 'ATTENTION-RECEIPT.ps1')
$release=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'HOLDING-MAINTENANCE-SOURCE.json') -Raw | ConvertFrom-Json
$expected=$null; $preservationFile=$null; $restart=$false; $restoreMonitor=$false; $lock=$null
$stage=Join-Path $env:TEMP ('cc-holding-tests-'+[guid]::NewGuid().ToString('N'))
function Import-HoldingBundle {
    param([string]$Bundle,[string]$Branch,[string]$Expected)
    # gc.auto=0 alone does not suppress incremental maintenance on recent Git.
    git -c maintenance.auto=false -c gc.auto=0 -c gc.autoPackLimit=0 -c fetch.writeCommitGraph=false fetch --no-auto-maintenance $Bundle ($Branch+':refs/test/holding-maintenance')
    if ($LASTEXITCODE -ne 0) { throw 'Native bundle import failed; source was not changed.' }
    $actual=(git rev-parse refs/test/holding-maintenance).Trim()
    if ($LASTEXITCODE -ne 0 -or $actual -ne $Expected) { throw 'Wrong maintenance source head.' }
}
function Assert-Idle {
    if (Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
        $_.Name -match '^python(w)?\.exe$' -and ([string]::IsNullOrWhiteSpace($_.CommandLine) -or $_.CommandLine -match 'bot\.py\b')
    }) { throw 'A bot command is running or cannot be inspected; no process was stopped.' }
    if (Get-ScheduledTask -ErrorAction Stop | Where-Object {
        $_.State -eq 'Running' -and ($_.TaskName -match '^CC bot\b' -or @($_.Actions | Where-Object { $_.Arguments -match 'bot\.py\b' }).Count -gt 0)
    }) { throw 'A bot task is running; retry after it finishes.' }
}
function Get-OwnedServer {
    $owned=Get-ScheduledTask -TaskName 'CC server' -ErrorAction Stop
    if (($owned.State -ne 'Running' -and $owned.State -ne 'Ready') -or !$owned.Settings.Enabled -or $owned.Actions.Count -ne 1 -or
        (Resolve-Path -LiteralPath $owned.Actions[0].Execute.Trim('"')).Path -ne $python -or
        $owned.Actions[0].Arguments -notmatch '^\s*(-u\s+)?-m\s+cc_server\.main\s*$' -or
        $owned.Actions[0].WorkingDirectory.TrimEnd('\') -ne $Repo.TrimEnd('\')) { throw 'Expected exact owned running CC server task.' }
    return $owned
}
function Wait-OwnedServer {
    $running=$null
    for ($i=0;$i -lt 20;$i++) {
        Get-OwnedServer | Out-Null
        try {
            $running=Invoke-RestMethod http://127.0.0.1:8585/api/health -TimeoutSec 3
            if ($running.ok -and [IO.Path]::GetFullPath($running.db) -eq (Join-Path $runtime 'cc.db')) { return }
        } catch { }
        Start-Sleep -Seconds 1
    }
    throw 'Server readiness unverified; preserve the receipt and installed source.'
}
function Assert-State {
    Assert-Idle
    $extra=@()
    if ($script:preservationFile) { $extra=@('--preserve',$script:preservationFile) }
    $raw=& $python -B (Join-Path $PSScriptRoot 'HOLDING-MAINTENANCE.py') $Repo @extra
    if ($LASTEXITCODE -ne 0) { throw "Maintenance refused: $raw" }
    $value=$raw | ConvertFrom-Json
    if ($value.fingerprint -notmatch '^[a-f0-9]{64}$') { throw 'Missing financial preservation fingerprint.' }
    if ($script:expected -and $value.fingerprint -ne $script:expected) { throw 'Financial records or controls changed; preserve receipt and investigate.' }
    $script:expected=$value.fingerprint
    return $value
}
Push-Location $Repo
try {
    if ((git branch --show-current).Trim() -ne 'feat/options-m7') { throw 'Expected feat/options-m7; no branch changed.' }
    foreach ($name in @('CHERRY_PICK_HEAD','MERGE_HEAD','REBASE_HEAD')) {
        if (Test-Path -LiteralPath (git rev-parse --git-path $name)) { throw 'Existing Git operation requires review; no reset attempted.' }
    }
    New-Item -ItemType Directory -Path (Join-Path $runtime 'monitor') -Force | Out-Null
    $lock=[IO.File]::Open((Join-Path $runtime 'monitor\holding-install.lock'),[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
    $initial=Assert-State
    $preservationFile=Join-Path $env:TEMP ('holding-preservation-'+[guid]::NewGuid().ToString('N')+'.json')
    $initial | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $preservationFile -Encoding UTF8
    $server=Get-OwnedServer
    if (!$Rollback -and $server.State -ne 'Running') { throw 'Installation requires the owned running server.' }
    $oldMonitor=Get-ScheduledTask -TaskName 'CC health monitor' -ErrorAction SilentlyContinue
    if ($oldMonitor -and ($oldMonitor.State -eq 'Running' -or !(Test-AttentionMonitorOwnership $oldMonitor $Repo $power))) { throw 'Monitor busy or ownership is unexpected; retry after its check finishes.' }
    if ($Rollback) {
        if (!$Receipt) { throw 'Rollback requires the printed recovery receipt directory.' }
        $saved=Get-Content -LiteralPath (Join-Path $Receipt 'receipt.json') -Raw | ConvertFrom-Json
        $commits=@(Get-AttentionRollbackCommits $saved $Repo)
        if ($commits.Count -gt 1) { throw 'Unexpected maintenance rollback history.' }
        if ($oldMonitor) {
            Disable-ScheduledTask -TaskName 'CC health monitor' | Out-Null; $restoreMonitor=$oldMonitor.Settings.Enabled
            if ((Get-ScheduledTask -TaskName 'CC health monitor').State -eq 'Running') { throw 'Monitor started during rollback preflight; retry after it finishes.' }
        }
        if ($server.State -eq 'Running') { Get-OwnedServer | Out-Null; Stop-ScheduledTask -TaskName 'CC server' }; $restart=$true
        for ($i=0;$i -lt 15;$i++) {
            if (!(Get-NetTCPConnection -LocalPort 8585 -State Listen -ErrorAction SilentlyContinue)) { break }
            Start-Sleep -Seconds 1
        }
        if (Get-NetTCPConnection -LocalPort 8585 -State Listen -ErrorAction SilentlyContinue) { throw 'Server port occupied; no process forced to stop.' }
        Assert-State | Out-Null
        if ($commits.Count -gt 0) {
            $actual=(git diff --binary ($commits[0]+'^') $commits[0]) -join "`n"
            $wanted=(git diff --binary $release.base $release.tip) -join "`n"
            if ($LASTEXITCODE -ne 0 -or $actual -cne $wanted) { throw 'Receipt commit differs from reviewed maintenance patch.' }
            git -c maintenance.auto=false -c gc.auto=0 -c gc.autoPackLimit=0 revert --no-edit $commits[0]
            if ($LASTEXITCODE -ne 0) { throw 'Rollback conflict; preserve checkout and receipt. No reset attempted.' }
        }
        foreach ($name in @('CC-MONITOR.py','CC-MONITOR.ps1','installed.json')) {
            $old=Join-Path $Receipt $name
            $target=Join-Path $runtime ('monitor\'+$name)
            if (Test-Path -LiteralPath $old) { Copy-Item -LiteralPath $old -Destination $target -Force }
            elseif ($name -eq 'installed.json') { Remove-Item -LiteralPath $target -ErrorAction SilentlyContinue }
        }
        if (Test-Path -LiteralPath (Join-Path $Receipt 'monitor-task.xml')) {
            Register-ScheduledTask -TaskName 'CC health monitor' -Xml (Get-Content -LiteralPath (Join-Path $Receipt 'monitor-task.xml') -Raw) -Force | Out-Null
        } elseif ($oldMonitor) { Unregister-ScheduledTask -TaskName 'CC health monitor' -Confirm:$false }
        $restoreMonitor=$false
        Assert-State | Out-Null
        Get-OwnedServer | Out-Null; Start-ScheduledTask -TaskName 'CC server'; $restart=$false
        Wait-OwnedServer
        Write-Host 'Maintenance source and previous monitor restored. Financial records, holding, stop and controls retained. Dashboard remains compatible with the older backend.'
        return
    }
    $health=Invoke-RestMethod http://127.0.0.1:8585/api/health -TimeoutSec 5
    if (!$health.ok -or [IO.Path]::GetFullPath($health.db) -ne (Join-Path $runtime 'cc.db')) { throw 'Running server does not match the repository.' }
    git bundle verify (Join-Path $PSScriptRoot 'holding-maintenance.bundle')
    if ($LASTEXITCODE -ne 0) { throw 'Maintenance bundle invalid.' }
    Import-HoldingBundle -Bundle (Join-Path $PSScriptRoot 'holding-maintenance.bundle') -Branch $release.branch -Expected $release.tip
    $paths=@(git diff --name-only $release.base $release.tip)
    $allowed=@($release.stages.installed.PSObject.Properties.Name)
    if ($LASTEXITCODE -ne 0 -or $paths.Count -ne $allowed.Count -or @($paths | Where-Object { $_ -notin $allowed }).Count -ne 0) { throw 'Maintenance source exceeds reviewed allowlist.' }
    New-Item -ItemType Directory -Path $stage | Out-Null
    git archive --format=tar --output=(Join-Path $stage 'source.tar') $release.tip
    if ($LASTEXITCODE -ne 0) { throw 'Source staging failed.' }
    & tar -xf (Join-Path $stage 'source.tar') -C $stage
    if ($LASTEXITCODE -ne 0) { throw 'Source extraction failed.' }
    $oldCCVar=$env:CC_VAR
    Push-Location $stage
    try {
        $env:CC_VAR=Join-Path $stage 'isolated-var'
        & $python -B -m pytest -q cc_sdk/tests/test_intraday.py cc_server/tests --basetemp (Join-Path $stage 'pytest-temp') -o ('cache_dir='+(Join-Path $stage 'pytest-cache'))
        if ($LASTEXITCODE -ne 0) { throw 'Staged regression failed; installed source unchanged.' }
    } finally {
        Pop-Location
        if ($null -eq $oldCCVar) { Remove-Item Env:\CC_VAR -ErrorAction SilentlyContinue } else { $env:CC_VAR=$oldCCVar }
    }
    Assert-State | Out-Null
    $backup=Join-Path $runtime ('backups\holding-maintenance-'+(Get-Date -Format 'yyyyMMdd-HHmmss-ffff'))
    New-Item -ItemType Directory -Path $backup | Out-Null
    if ($oldMonitor) {
        Export-ScheduledTask -TaskName 'CC health monitor' | Set-Content -LiteralPath (Join-Path $backup 'monitor-task.xml') -Encoding UTF8
        Disable-ScheduledTask -TaskName 'CC health monitor' | Out-Null
        $restoreMonitor=$oldMonitor.Settings.Enabled
        if ((Get-ScheduledTask -TaskName 'CC health monitor').State -eq 'Running') { throw 'Monitor started during preflight; retry after it finishes.' }
    }
    foreach ($name in @('CC-MONITOR.py','CC-MONITOR.ps1','installed.json')) {
        $file=Join-Path $runtime ('monitor\'+$name)
        if (Test-Path -LiteralPath $file) { Copy-Item -LiteralPath $file -Destination $backup }
    }
    $before=(git rev-parse HEAD).Trim()
    Save-AttentionReceipt -Repo $Repo -Backup $backup -Before $before -PendingCommit $release.tip
    Write-Host "Recovery receipt: $backup"
    Get-OwnedServer | Out-Null; Stop-ScheduledTask -TaskName 'CC server'; $restart=$true
    for ($i=0;$i -lt 15;$i++) {
        if (!(Get-NetTCPConnection -LocalPort 8585 -State Listen -ErrorAction SilentlyContinue)) { break }
        Start-Sleep -Seconds 1
    }
    if (Get-NetTCPConnection -LocalPort 8585 -State Listen -ErrorAction SilentlyContinue) { throw 'Server still owns port; no process forced to stop.' }
    Assert-State | Out-Null
    & $python -B (Join-Path $PSScriptRoot 'ATTENTION-PACKAGE.py') backup $runtime $backup
    if ($LASTEXITCODE -ne 0) { throw 'Consistent ledger backup failed.' }
    $initial | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $backup 'preservation.json') -Encoding UTF8
    if ($initial.source -eq 'before') {
        git -c maintenance.auto=false -c gc.auto=0 -c gc.autoPackLimit=0 cherry-pick $release.tip
        if ($LASTEXITCODE -ne 0) { throw 'Source conflict; preserve receipt and checkout. Do not reset.' }
    }
    Save-AttentionReceipt -Repo $Repo -Backup $backup -Before $before
    Assert-State | Out-Null
    Get-OwnedServer | Out-Null; Start-ScheduledTask -TaskName 'CC server'; $restart=$false
    Wait-OwnedServer
    & $power -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'APPLY-ATTENTION-DISPLAY.ps1') -Repo $Repo
    if ($LASTEXITCODE -ne 0) { throw 'Runtime installed; dashboard update needs review.' }
    & $power -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'INSTALL-CC-MONITOR.ps1') -Repo $Repo -Observation
    if ($LASTEXITCODE -ne 0) { throw 'Runtime installed; first incident observation needs review.' }
    $restoreMonitor=$false
    if ($Activate) {
        Start-Sleep -Seconds 2
        & $python -B (Join-Path $runtime 'monitor\CC-MONITOR.py') --repo $Repo
        if ($LASTEXITCODE -ne 0) { throw 'Second observation incomplete; recovery remains disabled.' }
        & $python -B (Join-Path $PSScriptRoot 'ATTENTION-PACKAGE.py') activate $Repo $runtime
        if ($LASTEXITCODE -ne 0) { throw 'Activation refused; monitoring remains in observation mode.' }
    }
    Assert-State | Out-Null
    Write-Host 'Holding-safe maintenance installed. Existing position, stop, financial history and risk pauses preserved.'
    Write-Host '30-second position observations and one-minute incident checks installed. Fresh market quotes and opening publication remain required.'
    Write-Host "Receipt: $backup"
} finally {
    if ($restart) { Get-OwnedServer | Out-Null; Start-ScheduledTask -TaskName 'CC server' -ErrorAction Continue }
    if ($restoreMonitor) { Enable-ScheduledTask -TaskName 'CC health monitor' -ErrorAction Continue | Out-Null }
    if ($lock) { $lock.Dispose() }
    if ($preservationFile) { Remove-Item -LiteralPath $preservationFile -ErrorAction SilentlyContinue }
    Pop-Location
    if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue }
}
