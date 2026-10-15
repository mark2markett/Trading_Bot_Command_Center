# Exercise the real preflight wrapper; simulate its external Python boundary only.
$ErrorActionPreference = 'Stop'
$installer = if ($env:CC_INSTALLER_TEST_PATH) { $env:CC_INSTALLER_TEST_PATH } else { Join-Path $PSScriptRoot 'APPLY-OCT14-NATIVE-FIXES.ps1' }
$source = Get-Content $installer -Raw
$begin = $source.IndexOf('function Assert-Preflight {')
$end = $source.IndexOf('Push-Location $Repo', $begin)
$body = $source.Substring($begin, $end-$begin).Replace('$PSScriptRoot', ("'" + $PSScriptRoot.Replace("'", "''") + "'"))
Invoke-Expression $body
function Assert-NoBotCommand { }
$python = 'Read-FakeGate'
$Repo = 'fixture'
function Read-FakeGate {
    $global:LASTEXITCODE = 0
    if ($args -contains '--git-only') { return '{"ok":true,"git":"ready"}' }
    return $script:nextGate | ConvertTo-Json -Compress
}
$script:expectedRuntime = $null
$script:nextGate = @{source='original';runtime_fingerprint=('a'*64)}
Assert-Preflight
$script:nextGate.source = 'installed'
Assert-Preflight -RequireInstalled
$script:nextGate.runtime_fingerprint = ('b'*64)
$blocked = $false
try { Assert-Preflight } catch { $blocked = $_.Exception.Message -match 'changed during installation' }
if (!$blocked) { throw 'A changed runtime snapshot was not blocked.' }
$script:expectedRuntime = $null
$script:nextGate.runtime_fingerprint = $null
$blocked = $false
try { Assert-Preflight } catch { $blocked = $_.Exception.Message -match 'fingerprint is missing' }
if (!$blocked) { throw 'Missing preservation evidence was not blocked.' }
$script:expectedRuntime = $null
$script:nextGate.runtime_fingerprint = ('a'*64)
$script:nextGate.source = 'original'
$blocked = $false
try { Assert-Preflight -RequireInstalled } catch { $blocked = $_.Exception.Message -match 'Installed source identity' }
if (!$blocked) { throw 'An uninstalled source stage was accepted as installed.' }
Write-Host 'PASS: stable runtime accepted; changed/missing runtime and uninstalled source refused (4 scenarios).'
