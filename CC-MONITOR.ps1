param([string]$Repo='C:\Users\Administrator\trading_bots\command-center')
$ErrorActionPreference='Stop'
$Repo=(Resolve-Path -LiteralPath $Repo).Path
$root=Join-Path $Repo 'var\monitor'
& (Join-Path $Repo '.venv\Scripts\python.exe') -B (Join-Path $root 'CC-MONITOR.py') --repo $Repo
exit $LASTEXITCODE
