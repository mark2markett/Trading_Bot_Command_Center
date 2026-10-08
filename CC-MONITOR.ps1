param([string]$Repo = 'C:\Users\Administrator\trading_bots\command-center')
$ErrorActionPreference = 'Stop'
$Repo = (Resolve-Path -LiteralPath $Repo).Path
$root = Join-Path $Repo 'var\monitor'
New-Item -ItemType Directory -Path $root -Force | Out-Null

# Recover only an enabled, stopped server task owned by this repository.
# A running but unresponsive server is reported; it is never force-stopped.
$responding = $false
try {
    $health = Invoke-RestMethod http://127.0.0.1:8585/api/health -TimeoutSec 5 -ErrorAction Stop
    $responding = $health.ok -eq $true
} catch { }
if (!$responding) {
    $server = Get-ScheduledTask -TaskName 'CC server' -ErrorAction SilentlyContinue
    $owned = ($server -and $server.Actions.Count -eq 1 -and
        $server.Actions[0].Arguments -match '-m\s+cc_server\.main\b' -and
        $server.Actions[0].WorkingDirectory.TrimEnd('\') -eq $Repo.TrimEnd('\'))
    if ($owned -and $server.Settings.Enabled -and $server.State -eq 'Ready') {
        $state = Join-Path $root 'server-recovery.json'
        $eligible = $true
        if (Test-Path -LiteralPath $state) {
            try {
                $last = Get-Content -LiteralPath $state -Raw | ConvertFrom-Json
                $elapsed = ([DateTimeOffset]::UtcNow - [DateTimeOffset]::Parse($last.at)).TotalMinutes
                $eligible = $elapsed -ge 30
            } catch { $eligible = $false }
        }
        if ($eligible) {
            @{at=[DateTimeOffset]::UtcNow.ToString('o'); action='start_enabled_stopped_server'} |
                ConvertTo-Json | Set-Content -LiteralPath $state -Encoding UTF8
            try {
                Start-ScheduledTask -TaskName 'CC server' -ErrorAction Stop
                Start-Sleep -Seconds 5
            } catch {
                @{at=[DateTimeOffset]::UtcNow.ToString('o'); action='server_start_failed'; error_type=$_.Exception.GetType().Name} |
                    ConvertTo-Json -Compress | Add-Content -LiteralPath (Join-Path $root 'recovery-errors.jsonl') -Encoding UTF8
            }
        }
    }
}

& (Join-Path $Repo '.venv\Scripts\python.exe') -B (Join-Path $root 'CC-MONITOR.py') --repo $Repo
exit $LASTEXITCODE
