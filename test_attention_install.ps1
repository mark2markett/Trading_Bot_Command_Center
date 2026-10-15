$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'ATTENTION-TASK-OWNERSHIP.ps1')
$root=Join-Path ([IO.Path]::GetTempPath()) ('attention-ownership-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $root | Out-Null
try {
    $power=Join-Path $root 'powershell.exe'; New-Item -ItemType File -Path $power | Out-Null
    $script=Join-Path $root 'var\monitor\CC-MONITOR.ps1'
    $argsText="-NoProfile -ExecutionPolicy Bypass -File `"$script`" -Repo `"$root`""
    $entry=[pscustomobject]@{Execute=$power;Arguments=$argsText;WorkingDirectory=$root}
    $task=[pscustomobject]@{Actions=@($entry)}
    if (!(Test-AttentionMonitorOwnership $task $root $power)) { throw 'Owned monitor must pass.' }
    $entry.Arguments=$argsText+' -Command bad'
    if (Test-AttentionMonitorOwnership $task $root $power) { throw 'Extra command must fail.' }
    $entry.Arguments=$argsText; $entry.WorkingDirectory='other'
    if (Test-AttentionMonitorOwnership $task $root $power) { throw 'Wrong working directory must fail.' }
    $entry.WorkingDirectory=$root; $entry.Execute='missing.exe'
    if (Test-AttentionMonitorOwnership $task $root $power) { throw 'Wrong executable must fail.' }
    Write-Host '4 monitor ownership scenarios passed.'
} finally { Remove-Item -LiteralPath $root -Recurse -Force }
