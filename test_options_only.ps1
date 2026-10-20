$ErrorActionPreference='Stop'
$testRoot=Join-Path ([IO.Path]::GetTempPath()) ('options-only-ps-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory $testRoot | Out-Null
try {
    foreach ($scenario in @('success','contain_failure','install_failure','activate_failure','verify_failure')) {
        $root=Join-Path $testRoot $scenario
        $repo=Join-Path $root 'owner checkout';$tools=Join-Path $root 'tools'
        New-Item -ItemType Directory (Join-Path $repo '.venv/Scripts') -Force | Out-Null
        New-Item -ItemType Directory $tools -Force | Out-Null
        Copy-Item (Join-Path $PSScriptRoot 'ENFORCE-OPTIONS-ONLY.ps1') $tools
        Set-Content (Join-Path $tools 'OPTIONS-ONLY.py') '# helper executable boundary is isolated below'
        $shim=@'
#!/usr/bin/env python3
import sys
from pathlib import Path
mode=sys.argv[3];repo=Path(sys.argv[sys.argv.index('--repo')+1])
with (repo/'calls.txt').open('a') as out:out.write(mode+'\n')
if repo.parent.name==mode+'_failure':raise SystemExit(1)
print('{"ok":true}')
'@
        $python=Join-Path $repo '.venv/Scripts/python.exe'
        [IO.File]::WriteAllText($python,$shim,[Text.UTF8Encoding]::new($false)); & chmod +x $python
        $install=@'
param($Repo)
Add-Content (Join-Path $Repo 'calls.txt') 'install'
if ((Split-Path (Split-Path $Repo) -Leaf) -eq 'install_failure') { throw 'isolated install failed' }
'@
        [IO.File]::WriteAllText((Join-Path $tools 'INSTALL-ACTIVITY-DASHBOARD.ps1'),$install)
        $lines=foreach($name in @('ENFORCE-OPTIONS-ONLY.ps1','OPTIONS-ONLY.py','INSTALL-ACTIVITY-DASHBOARD.ps1')){
            (Get-FileHash (Join-Path $tools $name)).Hash.ToLower()+'  '+$name
        }
        Set-Content (Join-Path $tools 'OPTIONS-ONLY-SHA256.txt') $lines
        $failed=$false
        try { & (Join-Path $tools 'ENFORCE-OPTIONS-ONLY.ps1') -Repo $repo } catch { $failed=$true }
        $calls=(Get-Content (Join-Path $repo 'calls.txt')) -join ','
        $expected=@{success='contain,install,activate,verify';contain_failure='contain';install_failure='contain,install';activate_failure='contain,install,activate';verify_failure='contain,install,activate,verify'}[$scenario]
        if($calls -ne $expected -or $failed -ne ($scenario -ne 'success')) { throw "Bad boundary order: $scenario calls=$calls failed=$failed" }
    }
    Write-Host 'PASS: five options-only installation boundary and failure scenarios.'
} finally { Remove-Item -LiteralPath $testRoot -Recurse -Force }
