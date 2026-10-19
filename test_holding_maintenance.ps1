$ErrorActionPreference='Stop'
$path=Join-Path $PSScriptRoot 'INSTALL-HOLDING-MAINTENANCE.ps1'
$tokens=$null;$errors=$null
$ast=[System.Management.Automation.Language.Parser]::ParseFile($path,[ref]$tokens,[ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
foreach ($name in @('Get-OwnedServer','Wait-OwnedServer','Assert-Idle')) {
    $definition=$ast.Find({param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name},$true)
    if (!$definition) { throw "Missing installer function: $name" }
    Invoke-Expression $definition.Extent.Text
}
$root=Join-Path ([IO.Path]::GetTempPath()) ('holding-task-test-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $root | Out-Null
$Repo=$root;$runtime=Join-Path $root 'var';$python=Join-Path $root 'python.exe'
New-Item -ItemType File -Path $python | Out-Null
$entry=[pscustomobject]@{Execute=$python;Arguments='-m cc_server.main';WorkingDirectory=$Repo}
$script:task=[pscustomobject]@{State='Running';Settings=[pscustomobject]@{Enabled=$true};Actions=@($entry)}
function Get-ScheduledTask { param($TaskName) return $script:task }
function Invoke-RestMethod { param($Uri,$TimeoutSec) return [pscustomobject]@{ok=$true;db=(Join-Path $runtime 'cc.db')} }
function Get-CimInstance { param($ClassName) return @() }
try {
    Get-OwnedServer | Out-Null
    Wait-OwnedServer
    Assert-Idle
    $entry.Arguments='-m bot.py'
    $refused=$false;try { Get-OwnedServer | Out-Null } catch { $refused=$true }
    if (!$refused) { throw 'Changed server action was accepted.' }
    $entry.Arguments='-m cc_server.main';$script:task.State='Ready'
    Get-OwnedServer | Out-Null
    $script:task.Settings.Enabled=$false
    $refused=$false;try { Get-OwnedServer | Out-Null } catch { $refused=$true }
    if (!$refused) { throw 'Disabled task accepted.' }
    $script:task.Settings.Enabled=$true
    function Get-CimInstance { param($ClassName) return [pscustomobject]@{Name='python.exe';CommandLine='python bot.py reconcile'} }
    $refused=$false;try { Assert-Idle } catch { $refused=$true }
    if (!$refused) { throw 'Running bot command accepted.' }
    Write-Host '6 holding-maintenance task/readiness scenarios passed.'
} finally { Remove-Item -LiteralPath $root -Recurse -Force }
