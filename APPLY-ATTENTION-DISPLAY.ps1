param([string]$Repo='C:\Users\Administrator\trading_bots\command-center')
$ErrorActionPreference='Stop'
$python=Join-Path $Repo '.venv\Scripts\python.exe'
if (!(Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Repository Python is missing.' }
& $python -B (Join-Path $PSScriptRoot 'APPLY-ATTENTION-DISPLAY.py') --repo $Repo
if ($LASTEXITCODE -ne 0) { throw 'Display update needs attention; preserve the printed output.' }
Write-Host 'Display-only update verified. Press Ctrl+F5. Bot source, orders, controls and running tasks were not changed.'
