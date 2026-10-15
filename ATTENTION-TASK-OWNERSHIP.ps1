function Test-AttentionMonitorOwnership {
    param($Task,[string]$Repo,[string]$PowerShell)
    if (!$Task -or $Task.Actions.Count -ne 1) { return $false }
    $entry=$Task.Actions[0]
    try { $execute=(Resolve-Path -LiteralPath ([Environment]::ExpandEnvironmentVariables($entry.Execute).Trim('"'))).Path } catch { return $false }
    $scriptPath=Join-Path $Repo 'var\monitor\CC-MONITOR.ps1'
    $pattern='^\s*-NoProfile\s+(?:-NonInteractive\s+)?-ExecutionPolicy\s+Bypass\s+-File\s+"'+[regex]::Escape($scriptPath)+'"\s+-Repo\s+"'+[regex]::Escape($Repo)+'"\s*$'
    return ($execute -eq $PowerShell -and $entry.WorkingDirectory.TrimEnd('\') -eq $Repo.TrimEnd('\') -and $entry.Arguments -match $pattern)
}
