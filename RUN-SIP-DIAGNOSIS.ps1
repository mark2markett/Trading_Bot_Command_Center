param([string]$Repo = 'C:\Users\Administrator\trading_bots\command-center')
$ErrorActionPreference = 'Stop'
$Repo = (Resolve-Path -LiteralPath $Repo).Path
$python = Join-Path $Repo '.venv\Scripts\python.exe'
if (!(Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Repository Python is missing.' }
foreach ($name in @('DIAGNOSE-SIP-OPENING.py', 'SIP-DIAGNOSTIC-UNIVERSE.json', 'test_sip_opening_probe.py')) {
    $entry = @(Get-Content -LiteralPath (Join-Path $PSScriptRoot 'SIP-PROBE-SHA256.txt') |
        Where-Object { $_ -match ('^[a-fA-F0-9]{64}\s+' + [regex]::Escape($name) + '$') })
    if ($entry.Count -ne 1 -or (Get-FileHash -LiteralPath (Join-Path $PSScriptRoot $name) -Algorithm SHA256).Hash -ne ($entry[0] -split '\s+')[0]) {
        throw "Diagnostic payload checksum mismatch: $name"
    }
}
$sandbox = Join-Path $env:TEMP ('cc-sip-probe-tests-' + [guid]::NewGuid().ToString('N'))
try {
    # Pass the SDK directory as argv: pytest's ini-path parser treats Windows backslashes as escapes.
    & $python -B -c 'import sys; sys.path.insert(0, sys.argv.pop(1)); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' (Join-Path $Repo 'cc_sdk') -q (Join-Path $PSScriptRoot 'test_sip_opening_probe.py') --basetemp $sandbox -o "cache_dir=$sandbox\cache"
    if ($LASTEXITCODE -ne 0) { throw 'Opening diagnostic regression tests failed.' }
} finally { Remove-Item -LiteralPath $sandbox -Recurse -Force -ErrorAction SilentlyContinue }
$eastern = [TimeZoneInfo]::FindSystemTimeZoneById('Eastern Standard Time')
$etNow = [TimeZoneInfo]::ConvertTimeFromUtc([DateTime]::UtcNow, $eastern)
Write-Host 'This uses the bots'' existing SDK connection (shared Schwab state or token broker). Existing OAuth handling and its issued-time sidecar may update; bots, orders and controls are preserved.'
Write-Host 'If preparation-cache access is absent, the probe checks 411 classified stocks at no more than one request per second, for at most ten minutes.'
if ($etNow.TimeOfDay -lt [TimeSpan]::FromHours(16.25)) {
    $server = Get-ScheduledTask -TaskName 'CC server' -ErrorAction Stop
    if ($server.Actions.Count -ne 1 -or $server.Actions[0].Arguments -notmatch '-m\s+cc_server\.main\b' -or
        $server.Actions[0].WorkingDirectory.TrimEnd('\') -ne $Repo.TrimEnd('\')) { throw 'Unexpected server task ownership.' }
    $day = $etNow.ToString('yyyy-MM-dd')
    $name = 'CC SIP opening diagnosis ' + $day
    $target = Join-Path $Repo ('var\sip-diagnosis-' + $day)
    $script = Join-Path $target 'DIAGNOSE-SIP-OPENING.py'
    $existing = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    if ($existing) {
        if ($existing.Actions.Count -ne 1 -or !$existing.Actions[0].Arguments.Contains($script)) { throw 'Unexpected existing diagnostic task ownership.' }
        if ($existing.State -eq 'Running') { Write-Host 'The owned diagnostic is already running.'; return }
    }
    New-Item -ItemType Directory -Path $target -Force | Out-Null
    foreach ($payload in @('DIAGNOSE-SIP-OPENING.py','SIP-DIAGNOSTIC-UNIVERSE.json')) {
        Copy-Item -LiteralPath (Join-Path $PSScriptRoot $payload) -Destination (Join-Path $target $payload) -Force
    }
    $at = [TimeZoneInfo]::ConvertTimeToUtc($etNow.Date.AddHours(16).AddMinutes(15), $eastern).ToLocalTime()
    $action = New-ScheduledTaskAction -Execute $python -Argument "-B `"$script`" --repo `"$Repo`" --date $day" -WorkingDirectory $Repo
    $trigger = New-ScheduledTaskTrigger -Once -At $at
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 15)
    Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings -Principal $server.Principal -Force | Out-Null
    Write-Host "Scheduled $name for 16:15 ET. Results will be saved to the task account's Desktop as CC-sip-opening-*.json."
    Write-Host 'The probe refuses to run if an intraday position remains open. Remain signed in for interactive tasks.'
} else {
    & $python -B (Join-Path $PSScriptRoot 'DIAGNOSE-SIP-OPENING.py') --repo $Repo
    if ($LASTEXITCODE -ne 0) { throw 'Diagnostic stopped; paste the output and retain the printed report.' }
}
