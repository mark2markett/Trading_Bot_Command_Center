param([string]$Repo)
$ErrorActionPreference = 'Stop'
if (!$Repo) {
    $Repo = Join-Path $env:TEMP ('m2m-sip-publish-' + [guid]::NewGuid().ToString('N'))
    git clone --single-branch --branch main 'https://github.com/mark2markett/m2m-platform.git' $Repo
    if ($LASTEXITCODE -ne 0) { throw 'Platform retrieval failed; use your normal authorized GitHub access.' }
    Write-Host "Isolated platform checkout: $Repo"
}
Set-Location -LiteralPath $Repo
$origin = (git remote get-url origin).Trim()
if ($LASTEXITCODE -ne 0 -or $origin -notmatch 'github\.com[:/]mark2markett/m2m-platform(?:\.git)?$') { throw 'Expected the mark2markett/m2m-platform origin.' }
$bundle = Join-Path $PSScriptRoot 'm2m-platform-sip-scanner.bundle'
git fetch origin main
if ($LASTEXITCODE -ne 0) { throw 'Could not retrieve platform history.' }
git bundle verify $bundle
if ($LASTEXITCODE -ne 0) { throw 'Platform bundle prerequisites are unavailable.' }
git fetch $bundle 'feat/cc-sip-scanner:feat/cc-sip-scanner'
if ($LASTEXITCODE -ne 0) { throw 'Feature branch import failed; no existing branch was overwritten.' }
git push origin 'feat/cc-sip-scanner:feat/cc-sip-scanner'
if ($LASTEXITCODE -ne 0) { throw 'Feature branch publication failed. No main merge or deployment was requested.' }
Write-Host 'Published the review branch; the current checkout was preserved.'
Write-Host 'Review: https://github.com/mark2markett/m2m-platform/compare/main...feat/cc-sip-scanner'
