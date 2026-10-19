$ErrorActionPreference='Stop'
$root=$PSScriptRoot
$test=Join-Path ([IO.Path]::GetTempPath()) ('overview-ps-'+[guid]::NewGuid().ToString('N'))
try {
    $repo=Join-Path $test 'owner checkout with spaces'
    New-Item -ItemType Directory (Join-Path $repo 'var/monitor') -Force | Out-Null
    New-Item -ItemType Directory (Join-Path $repo '.venv/Scripts') -Force | Out-Null
    $python=Join-Path $repo '.venv/Scripts/python.exe'
    $shim=@'
#!/usr/bin/env python3
import json,sys
from pathlib import Path
assert sys.argv[1]=='-B' and sys.argv[3]=='--repo' and len(sys.argv)==5,sys.argv
root=Path(sys.argv[4])
(root/'called.json').write_text(json.dumps(sys.argv[1:]))
print('{"ok":true,"scope":"DISPLAY_ONLY"}')
'@
    [IO.File]::WriteAllText($python,$shim,[Text.UTF8Encoding]::new($false))
    & chmod +x $python
    function Get-ScheduledTask { throw 'Display installer queried a task' }
    function Stop-ScheduledTask { throw 'Display installer stopped a task' }
    function Start-ScheduledTask { throw 'Display installer started a task' }
    function Disable-ScheduledTask { throw 'Display installer disabled a task' }
    & (Join-Path $root 'APPLY-TRADING-OVERVIEW.ps1') -Repo $repo
    if (!(Test-Path (Join-Path $repo 'called.json'))) { throw 'Python helper was not invoked.' }
    Remove-Item (Join-Path $repo 'called.json')
    $lock=[IO.File]::Open((Join-Path $repo 'var/monitor/holding-install.lock'),[IO.FileMode]::Open,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
    try {
        $refused=$false
        try { & (Join-Path $root 'APPLY-TRADING-OVERVIEW.ps1') -Repo $repo } catch { $refused=$true }
        if (!$refused -or (Test-Path (Join-Path $repo 'called.json'))) { throw 'Concurrent maintenance was not refused.' }
    } finally { $lock.Dispose() }
    Write-Host 'Display-only PowerShell invocation and shared maintenance lock passed; no task commands.'
} finally { if(Test-Path $test){Remove-Item -LiteralPath $test -Recurse -Force} }
