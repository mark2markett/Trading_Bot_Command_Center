param([string]$Repo, [switch]$UpdatePullRequestBody)
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
$bodyFile = Join-Path $PSScriptRoot 'SCANNER-PULL-REQUEST.md'
if ((Test-Path -LiteralPath $bodyFile) -and (Get-Command gh -ErrorAction SilentlyContinue)) {
    $existing = & gh pr list --repo mark2markett/m2m-platform --head feat/cc-sip-scanner --base main --state open --json url --jq '.[0].url' 2>$null
    if ($LASTEXITCODE -eq 0) {
        if ($existing) {
            Write-Host "Existing pull request: $existing"
            Write-Host "Acceptance mapping and review description: $bodyFile"
            if ($UpdatePullRequestBody) {
                $previousBody = & gh pr view $existing --repo mark2markett/m2m-platform --json body
                if ($LASTEXITCODE -eq 0) {
                    $bodyBackup = Join-Path (Join-Path $Repo '.git') ('cc-sip-pr-body-' + [guid]::NewGuid().ToString('N') + '.json')
                    $previousBody | Set-Content -LiteralPath $bodyBackup -Encoding UTF8
                    & gh pr edit $existing --repo mark2markett/m2m-platform --body-file $bodyFile
                    if ($LASTEXITCODE -ne 0) { Write-Warning 'Branch published; PR description update failed. Use the prepared description file.' }
                    else { Write-Host "PR description updated; previous body retained at $bodyBackup" }
                }
                else { Write-Warning 'Could not capture the existing PR description; it was not overwritten.' }
            }
        }
        else {
            & gh pr create --repo mark2markett/m2m-platform --base main --head feat/cc-sip-scanner --title 'Restore Command Center SIP ORB scanner input' --body-file $bodyFile
            if ($LASTEXITCODE -ne 0) { Write-Warning 'Branch published; PR creation requires your normal authorized GitHub login. Use the review URL and description file.' }
        }
    }
    else { Write-Warning 'Branch published; GitHub CLI API access is unavailable. Use the review URL and description file.' }
}
Write-Host "PR description: $bodyFile"
Write-Host 'Do not merge until current-head GitHub review, required checks and preview pass. This command does not deploy or change secrets.'
