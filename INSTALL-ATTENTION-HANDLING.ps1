param([string]$Repo='C:\Users\Administrator\trading_bots\command-center',
      [switch]$Activate,[switch]$Rollback,[string]$Receipt)
$ErrorActionPreference='Stop'
$Repo=(Resolve-Path -LiteralPath $Repo).Path
$python=Join-Path $Repo '.venv\Scripts\python.exe'
$runtime=Join-Path $Repo 'var'
if ($env:CC_VAR -and [IO.Path]::GetFullPath($env:CC_VAR).TrimEnd('\') -ne $runtime.TrimEnd('\')) { throw 'This installer requires the repository var directory; custom CC_VAR was preserved.' }
$monitor=Join-Path $runtime 'monitor'
$expectedRuntime=$null
function Assert-Preflight {
    Assert-NoBotCommand
    $raw=& $python -B (Join-Path $PSScriptRoot 'ATTENTION-PREFLIGHT.py') $Repo
    if ($LASTEXITCODE -ne 0) { throw "Installation preflight refused: $raw" }
    $value=$raw | ConvertFrom-Json
    if ($value.runtime_fingerprint -notmatch '^[a-f0-9]{64}$') { throw 'Missing runtime preservation fingerprint.' }
    if ($script:expectedRuntime -and $script:expectedRuntime -ne $value.runtime_fingerprint) { throw 'Runtime state changed; no further source changes permitted.' }
    $script:expectedRuntime=$value.runtime_fingerprint
    return $value
}
function Invoke-StagedNativeTests {
    param([string]$SourceStage, [string]$TestRuntime, [string]$Commit, [string]$Python)
    New-Item -ItemType Directory -Path $SourceStage, $TestRuntime | Out-Null
    $archive = Join-Path $SourceStage 'source.tar'
    # Archive canonical Git bytes, independently of Windows working-tree defaults.
    git -c core.autocrlf=false archive --format=tar --output=$archive $Commit
    if ($LASTEXITCODE -ne 0) { throw 'Source staging failed.' }
    & tar -xf $archive -C $SourceStage
    if ($LASTEXITCODE -ne 0) { throw 'Source extraction failed.' }
    $previousCCVar = $env:CC_VAR
    Push-Location $SourceStage
    try {
        $env:CC_VAR = Join-Path $TestRuntime 'var'
        $pytestTemp = Join-Path $TestRuntime 'pytest-temp'
        $pytestCache = Join-Path $TestRuntime 'pytest-cache'
        & $Python -B -m pytest -q --basetemp $pytestTemp -o ("cache_dir=" + $pytestCache)
        if ($LASTEXITCODE -ne 0) { throw 'Staged native regression failed; installed source was not changed.' }
    } finally {
        Pop-Location
        if ($null -eq $previousCCVar) { Remove-Item Env:\CC_VAR -ErrorAction SilentlyContinue } else { $env:CC_VAR = $previousCCVar }
    }
}
function Assert-NoBotCommand {
    if (Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
        $_.Name -match '^python(w)?\.exe$' -and
        ([string]::IsNullOrWhiteSpace($_.CommandLine) -or $_.CommandLine -match 'bot\.py\b')
    }) { throw 'A bot command is running or cannot be inspected; no processes were stopped. Install after commands finish.' }
    if (Get-ScheduledTask -ErrorAction Stop | Where-Object {
        $_.State -eq 'Running' -and ($_.TaskName -match '^CC bot\b' -or
            @($_.Actions | Where-Object { $_.Arguments -match 'bot\.py\b' }).Count -gt 0)
    }) { throw 'A bot task is running; install after it finishes.' }
}
foreach ($line in Get-Content -LiteralPath (Join-Path $PSScriptRoot 'ATTENTION-SHA256.txt')) {
    if ($line -notmatch '^([a-f0-9]{64})\s+([A-Za-z0-9_.-]+)$') { throw 'Invalid release manifest entry.' }
    if ((Get-FileHash -LiteralPath (Join-Path $PSScriptRoot $Matches[2])).Hash -ne $Matches[1]) { throw 'Release checksum mismatch.' }
}
. (Join-Path $PSScriptRoot 'ATTENTION-TASK-OWNERSHIP.ps1')
. (Join-Path $PSScriptRoot 'ATTENTION-RECEIPT.ps1')
$power=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$release=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'ATTENTION-NATIVE-SOURCE.json') -Raw | ConvertFrom-Json
$stage=Join-Path $env:TEMP ('attention-source-'+[guid]::NewGuid().ToString('N'))
$testRoot=Join-Path $env:TEMP ('attention-tests-'+[guid]::NewGuid().ToString('N'))
$restart=$false
$restoreMonitor=$false
Push-Location $Repo
try {
    if ((git branch --show-current).Trim() -ne 'feat/options-m7') { throw 'Expected feat/options-m7; no branch was changed.' }
    foreach ($state in @('CHERRY_PICK_HEAD','MERGE_HEAD','REBASE_HEAD')) {
        $file=git rev-parse --git-path $state
        if (Test-Path -LiteralPath $file) { throw 'Finish the existing Git operation first.' }
    }
    $preflight=Assert-Preflight
    if (!$Rollback -and $preflight.source -like 'step_*') { throw 'A previous installation is incomplete. Use its existing rollback receipt; no source was changed.' }
    $server=Get-ScheduledTask -TaskName 'CC server' -ErrorAction Stop
    if ($server.Actions.Count -ne 1 -or !$server.Settings.Enabled -or
        (Resolve-Path -LiteralPath $server.Actions[0].Execute.Trim('"')).Path -ne $python -or
        $server.Actions[0].Arguments -notmatch '^\s*(-u\s+)?-m\s+cc_server\.main\s*$' -or
        $server.Actions[0].WorkingDirectory.TrimEnd('\') -ne $Repo.TrimEnd('\')) { throw 'Expected owned running server task.' }
    $oldMonitor=Get-ScheduledTask -TaskName 'CC health monitor' -ErrorAction SilentlyContinue
    if ($oldMonitor -and ($oldMonitor.State -eq 'Running' -or !(Test-AttentionMonitorOwnership $oldMonitor $Repo $power))) { throw 'Monitor is running or has unexpected ownership; retry after it finishes.' }
    if ($Rollback) {
        if (!$Receipt) { throw 'Rollback requires the printed receipt directory.' }
        $saved=Get-Content -LiteralPath (Join-Path $Receipt 'receipt.json') -Raw | ConvertFrom-Json
        if ($preflight.source -ne 'installed' -and $preflight.source -ne 'before' -and $preflight.source -notlike 'step_*') { throw 'Unknown rollback source stage.' }
        $commits=@(Get-AttentionRollbackCommits $saved $Repo)
        if ($oldMonitor) { Disable-ScheduledTask -TaskName 'CC health monitor' | Out-Null }
        if ($server.State -eq 'Running') { Stop-ScheduledTask -TaskName 'CC server' } elseif ($server.State -ne 'Ready') { throw 'Server task state is ambiguous.' }; $restart=$true
        for ($i=0;$i -lt 15;$i++) { if (!(Get-NetTCPConnection -LocalPort 8585 -State Listen -ErrorAction SilentlyContinue)) { break }; Start-Sleep -Seconds 1 }
        if (Get-NetTCPConnection -LocalPort 8585 -State Listen -ErrorAction SilentlyContinue) { throw 'Server port is still occupied.' }
        Assert-Preflight | Out-Null
        [array]::Reverse($commits)
        if ($commits.Count -gt 0) { git revert --no-edit @commits }
        if ($commits.Count -gt 0 -and $LASTEXITCODE -ne 0) { throw 'Rollback conflict; preserve checkout and receipt. No reset was attempted.' }
        if (Test-Path -LiteralPath (Join-Path $Receipt 'dist')) {
            Remove-Item -LiteralPath (Join-Path $Repo 'cc_web\dist') -Recurse -Force
            Copy-Item -LiteralPath (Join-Path $Receipt 'dist') -Destination (Join-Path $Repo 'cc_web\dist') -Recurse
        }
        foreach ($name in @('CC-MONITOR.py','CC-MONITOR.ps1','installed.json')) {
            $old=Join-Path $Receipt $name
            if (Test-Path -LiteralPath $old) { Copy-Item -LiteralPath $old -Destination (Join-Path $monitor $name) -Force }
            elseif ($name -eq 'installed.json') { Remove-Item -LiteralPath (Join-Path $monitor $name) -ErrorAction SilentlyContinue }
        }
        if (Test-Path -LiteralPath (Join-Path $Receipt 'monitor-task.xml')) {
            Register-ScheduledTask -TaskName 'CC health monitor' -Xml (Get-Content -LiteralPath (Join-Path $Receipt 'monitor-task.xml') -Raw) -Force | Out-Null
        } elseif ($oldMonitor) { Unregister-ScheduledTask -TaskName 'CC health monitor' -Confirm:$false }
        Start-ScheduledTask -TaskName 'CC server'; $restart=$false
        Write-Host 'Previous owned monitor/source restored; incident history and trading state retained.'
        return
    }
    if ($server.State -ne 'Running') { throw 'Installation requires the owned running server; use -Rollback for a failed installation.' }
    git bundle verify (Join-Path $PSScriptRoot 'attention-native.bundle')
    if ($LASTEXITCODE -ne 0) { throw 'Native bundle verification failed.' }
    git -c gc.auto=0 fetch (Join-Path $PSScriptRoot 'attention-native.bundle') ($release.branch+':test/attention-native')
    if ($LASTEXITCODE -ne 0) { throw 'Could not import reviewed source.' }
    $actual=(git rev-parse test/attention-native).Trim()
    if ($actual -ne $release.tip) { throw 'Unexpected native release head.' }
    $paths=@(git diff --name-only $release.base $release.tip)
    $allowed=@($release.stages.installed.PSObject.Properties.Name)
    if ($paths.Count -ne $allowed.Count -or @($paths | Where-Object { $_ -notin $allowed }).Count -ne 0) { throw 'Source exceeds reviewed allowlist.' }
    Invoke-StagedNativeTests -SourceStage $stage -TestRuntime $testRoot -Commit $release.tip -Python $python
    Assert-Preflight | Out-Null
    $backup=Join-Path $runtime ('backups\attention-'+(Get-Date -Format 'yyyyMMdd-HHmmss-ffff'))
    New-Item -ItemType Directory -Path $backup -Force | Out-Null
    if ($oldMonitor) { Export-ScheduledTask -TaskName 'CC health monitor' | Set-Content -LiteralPath (Join-Path $backup 'monitor-task.xml') -Encoding UTF8; Disable-ScheduledTask -TaskName 'CC health monitor' | Out-Null; $restoreMonitor=$true }
    foreach ($name in @('CC-MONITOR.py','CC-MONITOR.ps1','installed.json')) {
        if (Test-Path -LiteralPath (Join-Path $monitor $name)) { Copy-Item -LiteralPath (Join-Path $monitor $name) -Destination $backup }
    }
    if (Test-Path -LiteralPath (Join-Path $Repo 'cc_web\dist')) { Copy-Item -LiteralPath (Join-Path $Repo 'cc_web\dist') -Destination (Join-Path $backup 'dist') -Recurse }
    & $python -B (Join-Path $PSScriptRoot 'ATTENTION-PACKAGE.py') backup $runtime $backup
    if ($LASTEXITCODE -ne 0) { throw 'Consistent runtime backups failed.' }
    $before=(git rev-parse HEAD).Trim()
    Save-AttentionReceipt -Repo $Repo -Backup $backup -Before $before
    Write-Host "Recovery receipt (retained if installation stops): $backup"
    $expectedHead=$before
    if ($preflight.source -ne 'installed') {
        Stop-ScheduledTask -TaskName 'CC server'; $restart=$true
        for ($i=0;$i -lt 15;$i++) { if (!(Get-NetTCPConnection -LocalPort 8585 -State Listen -ErrorAction SilentlyContinue)) { break }; Start-Sleep -Seconds 1 }
        if (Get-NetTCPConnection -LocalPort 8585 -State Listen -ErrorAction SilentlyContinue) { throw 'Server port is still occupied; no process was forced to stop.' }
        Assert-Preflight | Out-Null
        foreach ($commit in @(git rev-list --reverse ($release.base+'..'+$release.tip))) {
            if ((git rev-parse HEAD).Trim() -ne $expectedHead) { throw 'Source head changed during installation; preserve the receipt.' }
            Save-AttentionReceipt -Repo $Repo -Backup $backup -Before $before -PendingCommit $commit
            git -c gc.auto=0 cherry-pick $commit
            if ($LASTEXITCODE -ne 0) { throw 'Source conflict; preserve checkout and paste output. Do not reset.' }
            $expectedHead=(git rev-parse HEAD).Trim()
            Save-AttentionReceipt -Repo $Repo -Backup $backup -Before $before
        }
        Assert-Preflight | Out-Null
    }
    & $python -B (Join-Path $PSScriptRoot 'ATTENTION-PACKAGE.py') extract (Join-Path $PSScriptRoot 'attention-dashboard.zip') (Join-Path $Repo 'cc_web\dist')
    if ($LASTEXITCODE -ne 0) { throw 'Dashboard extraction failed.' }
    if ($restart) { Start-ScheduledTask -TaskName 'CC server'; $restart=$false }
    $health=$null
    for ($i=0;$i -lt 15;$i++) {
        try { $health=Invoke-RestMethod http://127.0.0.1:8585/api/health -TimeoutSec 3; if ($health.ok) { break } } catch { }
        Start-Sleep -Seconds 2
    }
    if (!$health.ok) { throw 'Server health needs review; source and backups retained.' }
    & (Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe') -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'INSTALL-CC-MONITOR.ps1') -Repo $Repo -Observation
    if ($LASTEXITCODE -ne 0) { throw 'Observation monitor needs review.' }
    $restoreMonitor=$false
    $commits=@(git rev-list --reverse ($before+'..HEAD'))
    Save-AttentionReceipt -Repo $Repo -Backup $backup -Before $before
    Write-Host "Rollback receipt: $backup"
    if ($Activate) {
        Start-Sleep -Seconds 2
        & $python -B (Join-Path $monitor 'CC-MONITOR.py') --repo $Repo
        if ($LASTEXITCODE -ne 0) { throw 'Second observation failed; recovery remains disabled.' }
        & $python -B (Join-Path $PSScriptRoot 'ATTENTION-PACKAGE.py') activate $Repo $runtime
        if ($LASTEXITCODE -ne 0) { throw 'Activation refused; monitor continues observing.' }
        Write-Host 'Limited server recovery and configured notification routing enabled. No test message sent.'
    }
    Assert-Preflight | Out-Null
    Write-Host 'One-minute incident monitoring installed. Trading state, bot tasks and existing controls preserved.'
} finally {
    if ($restart) { Start-ScheduledTask -TaskName 'CC server' -ErrorAction Continue }
    if ($restoreMonitor -and $oldMonitor -and $oldMonitor.Settings.Enabled) { Enable-ScheduledTask -TaskName 'CC health monitor' -ErrorAction Continue | Out-Null }
    Pop-Location
    foreach ($temporary in @($stage,$testRoot)) { if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Recurse -Force -ErrorAction SilentlyContinue } }
}
