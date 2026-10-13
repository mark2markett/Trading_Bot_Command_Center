# Owner release step for the October 13 SIP publication repair, PR 1296. Invoke only after Mark reviews:
# https://github.com/mark2markett/m2m-platform/pull/1296 (current-head Codex review)
# No Windows bot source, tasks, controls, capital or positions are changed.
$ErrorActionPreference = 'Stop'
$repo = 'mark2markett/m2m-platform'
$expected = '8d110664fe5f7ff15b3bb08b78446d824c98ae08'
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
    $pullJson = & gh pr view 1296 --repo $repo --json state,headRefOid,mergeable,mergeStateStatus
    if ($LASTEXITCODE -ne 0) { throw 'Could not verify current PR mergeability. No merge was attempted.' }
    $pull = $pullJson | ConvertFrom-Json
    if ($pull.headRefOid -ne $expected) { throw 'PR head changed. Current-head review is required.' }
    if ($pull.state -eq 'OPEN') {
        $release = Join-Path $env:TEMP ('cc-sip-latency-owner-release-' + [guid]::NewGuid().ToString('N'))
        git clone --depth 1 --single-branch --branch fix/sip-publication-latency-20261013 "https://github.com/$repo.git" $release
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
        & node scripts/delivery-gate.mjs readiness 1296
        if ($LASTEXITCODE -ne 0) { throw 'Canonical readiness failed. No merge was attempted.' }
        Write-Host 'Review: https://github.com/mark2markett/m2m-platform/pull/1296. The current-head review has no blockers; owner merge acknowledges its two concerns: decision-ledger placement and conservative failure if a cache key appears between MGET and EXISTS. See SIP-OCT13-REPAIR.md.'
        & gh pr merge 1296 --repo $repo --squash --match-head-commit $expected
        if ($LASTEXITCODE -ne 0) { throw 'Owner merge failed; required checks were not bypassed.' }
    }
    elseif ($pull.state -eq 'MERGED') {
        Write-Host 'The pinned PR is already merged; verifying deployment only.'
    }
    else { throw 'The pinned PR is closed without merging. No merge was attempted.' }
    $mergedJson = & gh pr view 1296 --repo $repo --json state,url,mergeCommit
    if ($LASTEXITCODE -ne 0) { throw 'Could not read the merge result; inspect PR 1296.' }
    $merged = $mergedJson | ConvertFrom-Json
    if ($merged.state -ne 'MERGED' -or -not $merged.mergeCommit.oid) {
        throw 'Merge is not confirmed. No deployment claim is made.'
    }
    $mergedJson | Write-Host
    $deadline = (Get-Date).AddMinutes(10)
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
    Write-Host 'Platform release and reported health verified. Paper-testing exclusions end after October 16; strict completeness resumes October 19. Native v1 needs no code patch. Verify authenticated current-session publication and native SIP selection at 09:35-09:39 ET; several clean paper sessions remain to be observed.'
}
finally {
    [Environment]::SetEnvironmentVariable('GH_TOKEN', $previousGhToken, 'Process')
    $ownerToken = $null
    if ($locationChanged) { Pop-Location }
}
