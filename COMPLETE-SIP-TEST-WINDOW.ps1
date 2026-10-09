# Owner release step for reviewed PR 1280. Invoke only after Mark reviews:
# https://github.com/mark2markett/m2m-platform/pull/1280#issuecomment-6079737534
# No Windows bot source, tasks, controls, capital or positions are changed.
$ErrorActionPreference = 'Stop'
$repo = 'mark2markett/m2m-platform'
$expected = '88967dc555ba4c5cd938dde04638c12983b6b75d'
$release = Join-Path $env:TEMP ('cc-sip-owner-release-' + [guid]::NewGuid().ToString('N'))

git clone --depth 1 --single-branch --branch fix/sip-testing-four-exclusions "https://github.com/$repo.git" $release
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
    $pullJson = & gh pr view 1280 --repo $repo --json headRefOid,mergeable,mergeStateStatus
    if ($LASTEXITCODE -ne 0) { throw 'Could not verify current PR mergeability. No merge was attempted.' }
    $pull = $pullJson | ConvertFrom-Json
    if ($pull.headRefOid -ne $expected) { throw 'PR head changed. Current-head review is required.' }
    if ($pull.mergeable -ne 'MERGEABLE') {
        throw "PR is not currently mergeable ($($pull.mergeable)); resolve conflicts or retry after GitHub finishes computing it. No merge was attempted."
    }
    & node scripts/delivery-gate.mjs readiness 1280
    if ($LASTEXITCODE -ne 0) { throw 'Canonical readiness failed. No merge was attempted.' }
    & gh pr merge 1280 --repo $repo --squash --match-head-commit $expected
    if ($LASTEXITCODE -ne 0) { throw 'Owner merge failed; required checks were not bypassed.' }
    & gh pr view 1280 --repo $repo --json state,url,mergeCommit
    if ($LASTEXITCODE -ne 0) { throw 'Could not read the merge result; inspect PR 1280.' }
    Write-Host 'Owner merge requested. Verify production deployment of the returned merge commit before the morning run.'
}
finally {
    [Environment]::SetEnvironmentVariable('GH_TOKEN', $previousGhToken, 'Process')
    $ownerToken = $null
    Pop-Location
}
