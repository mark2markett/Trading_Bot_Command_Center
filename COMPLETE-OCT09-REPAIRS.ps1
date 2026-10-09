# Owner release step for the combined October 9 repairs, PR 1287. Invoke only after Mark reviews:
# https://github.com/mark2markett/m2m-platform/pull/1287 (current-head Codex review)
# No Windows bot source, tasks, controls, capital or positions are changed.
$ErrorActionPreference = 'Stop'
$repo = 'mark2markett/m2m-platform'
$expected = 'bc70dcd5bf3bfd299493a64a0187088d34e0b08a'
$previousGhToken = [Environment]::GetEnvironmentVariable('GH_TOKEN', 'Process')
$locationChanged = $false
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
    $pullJson = & gh pr view 1287 --repo $repo --json state,headRefOid,mergeable,mergeStateStatus
    if ($LASTEXITCODE -ne 0) { throw 'Could not verify current PR mergeability. No merge was attempted.' }
    $pull = $pullJson | ConvertFrom-Json
    if ($pull.headRefOid -ne $expected) { throw 'PR head changed. Current-head review is required.' }
    if ($pull.state -eq 'OPEN') {
        $release = Join-Path $env:TEMP ('cc-oct09-owner-release-' + [guid]::NewGuid().ToString('N'))
        git clone --depth 1 --single-branch --branch fix/sip-opening-failure-context "https://github.com/$repo.git" $release
        if ($LASTEXITCODE -ne 0) { throw 'Release checkout failed. No merge was attempted.' }
        $head = git -C $release rev-parse HEAD
        if ($LASTEXITCODE -ne 0 -or $head.Trim() -ne $expected) {
            throw 'The review branch changed. Obtain current-head review before merging.'
        }
        Push-Location $release
        $locationChanged = $true
        if ($pull.mergeable -ne 'MERGEABLE') {
            throw "PR is not currently mergeable ($($pull.mergeable)); resolve conflicts or retry after GitHub finishes computing it. No merge was attempted."
        }
        & node scripts/delivery-gate.mjs readiness 1287
        if ($LASTEXITCODE -ne 0) { throw 'Canonical readiness failed. No merge was attempted.' }
        & gh pr merge 1287 --repo $repo --squash --match-head-commit $expected
        if ($LASTEXITCODE -ne 0) { throw 'Owner merge failed; required checks were not bypassed.' }
    }
    elseif ($pull.state -eq 'MERGED') {
        Write-Host 'The pinned PR is already merged; verifying deployment only.'
    }
    else { throw 'The pinned PR is closed without merging. No merge was attempted.' }
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
    if (-not $verified) { throw 'Merge completed, but production release/health is still unverified. Rerun this helper to verify deployment only; it will not repeat the merge.' }
    Write-Host 'This verifies platform deployment and reported health. Authenticated SIP publication and native consumption must still pass in the next opening window; several clean paper sessions remain to be observed.'
}
finally {
    [Environment]::SetEnvironmentVariable('GH_TOKEN', $previousGhToken, 'Process')
    $ownerToken = $null
    if ($locationChanged) { Pop-Location }
}
