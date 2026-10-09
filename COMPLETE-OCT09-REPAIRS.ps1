# Owner release step for the combined October 9 repairs, PR 1287. Invoke only after Mark reviews:
# https://github.com/mark2markett/m2m-platform/pull/1287 (current-head Codex review)
# No Windows bot source, tasks, controls, capital or positions are changed.
$ErrorActionPreference = 'Stop'
$repo = 'mark2markett/m2m-platform'
$expected = '0dbcd53c3615b8190d01b6d9f622c06a7ff9c5f9'
$release = Join-Path $env:TEMP ('cc-oct09-owner-release-' + [guid]::NewGuid().ToString('N'))

git clone --depth 1 --single-branch --branch fix/sip-opening-failure-context "https://github.com/$repo.git" $release
if ($LASTEXITCODE -ne 0) { throw 'Release checkout failed. No merge was attempted.' }
$head = git -C $release rev-parse HEAD
if ($LASTEXITCODE -ne 0 -or $head.Trim() -ne $expected) {
    throw 'The review branch changed. Obtain current-head review before merging.'
}

$previousGhToken = [Environment]::GetEnvironmentVariable('GH_TOKEN', 'Process')
Push-Location $release
try {
    $ownerToken = & gh auth token
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($ownerToken)) {
        throw 'Owner GitHub authentication unavailable. No merge was attempted.'
    }
    $env:GH_TOKEN = $ownerToken.Trim()
    $owner = & gh api user --jq '.login'
    if ($LASTEXITCODE -ne 0 -or $owner.Trim() -ne 'mark2markett') {
        throw 'Repository rules require Mark to perform this owner merge.'
    }
    $pullJson = & gh pr view 1287 --repo $repo --json headRefOid,mergeable,mergeStateStatus
    if ($LASTEXITCODE -ne 0) { throw 'Could not verify current PR mergeability. No merge was attempted.' }
    $pull = $pullJson | ConvertFrom-Json
    if ($pull.headRefOid -ne $expected) { throw 'PR head changed. Current-head review is required.' }
    if ($pull.mergeable -ne 'MERGEABLE') {
        throw "PR is not currently mergeable ($($pull.mergeable)); resolve conflicts or retry after GitHub finishes computing it. No merge was attempted."
    }
    & node scripts/delivery-gate.mjs readiness 1287
    if ($LASTEXITCODE -ne 0) { throw 'Canonical readiness failed. No merge was attempted.' }
    & gh pr merge 1287 --repo $repo --squash --match-head-commit $expected
    if ($LASTEXITCODE -ne 0) { throw 'Owner merge failed; required checks were not bypassed.' }
    $mergedJson = & gh pr view 1287 --repo $repo --json state,url,mergeCommit
    if ($LASTEXITCODE -ne 0) { throw 'Could not read the merge result; inspect PR 1287.' }
    $merged = $mergedJson | ConvertFrom-Json
    if ($merged.state -ne 'MERGED' -or -not $merged.mergeCommit.oid) {
        throw 'Merge is not confirmed. No deployment claim is made.'
    }
    $mergedJson | Write-Host
    $deadline = (Get-Date).AddMinutes(5)
    $verified = $false
    do {
        try {
            $health = Invoke-RestMethod 'https://www.mark2markets.com/api/healthcheck' -TimeoutSec 15 -ErrorAction Stop
            if ($health.release.state -eq 'known' -and
                $health.release.sha -eq $merged.mergeCommit.oid -and
                $health.ok -eq $true -and $health.checks.enrich_recent -eq $true) {
                $verified = $true
                Write-Host ('Production health passed on merge commit ' + $merged.mergeCommit.oid)
                break
            }
        }
        catch { Write-Host 'Production health is not yet verified.' }
        if ((Get-Date) -lt $deadline) { Start-Sleep -Seconds 5 }
    } while ((Get-Date) -lt $deadline)
    if (-not $verified) { throw 'Merge completed, but production release/health is still unverified. Do not repeat the merge.' }
    Write-Host 'This verifies platform deployment and reported health. Authenticated SIP publication and native consumption must still pass in the next opening window; several clean paper sessions remain to be observed.'
}
finally {
    [Environment]::SetEnvironmentVariable('GH_TOKEN', $previousGhToken, 'Process')
    $ownerToken = $null
    Pop-Location
}
