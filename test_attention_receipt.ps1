param([string]$NativeRepo='/workspace/scratch/cc-dashboard-wrap-20261007')
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'ATTENTION-RECEIPT.ps1')
$root=Join-Path ([IO.Path]::GetTempPath()) ('attention-receipt-'+[guid]::NewGuid().ToString('N'))
$repo=Join-Path $root 'repo'; $backup=Join-Path $root 'backup'
New-Item -ItemType Directory -Path $backup -Force | Out-Null
try {
    git clone --quiet --no-hardlinks $NativeRepo $repo
    if ($LASTEXITCODE -ne 0) { throw 'Fixture clone failed.' }
    Push-Location $repo
    try {
        git config user.name 'Receipt rehearsal'; git config user.email 'receipt@example.invalid'
        $before='dbea1523259e8c7cafd6579ed083eb40da0a7c28'
        $candidate=@(git rev-list --reverse ($before+'..HEAD'))[0]
        git checkout --quiet --detach $before
        Save-AttentionReceipt $repo $backup $before
        $saved=Get-Content -LiteralPath (Join-Path $backup 'receipt.json') -Raw | ConvertFrom-Json
        if ($saved.installed_head -ne $before -or @($saved.commits).Count -ne 0) { throw 'Before-mutation receipt invalid.' }
        Save-AttentionReceipt $repo $backup $before $candidate
        git cherry-pick $candidate | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Fixture cherry-pick failed.' }
        $saved=Get-Content -LiteralPath (Join-Path $backup 'receipt.json') -Raw | ConvertFrom-Json
        $actual=@(Get-AttentionRollbackCommits $saved $repo)
        if ($actual.Count -ne 1 -or $actual[0] -ne (git rev-parse HEAD).Trim()) { throw 'Unrecorded reviewed commit not recoverable.' }
        Save-AttentionReceipt $repo $backup $before
        $saved=Get-Content -LiteralPath (Join-Path $backup 'receipt.json') -Raw | ConvertFrom-Json
        if (@(Get-AttentionRollbackCommits $saved $repo).Count -ne 1) { throw 'Completed partial receipt not recoverable.' }
        Set-Content -LiteralPath 'owner-extra.txt' -Value 'owner change'; git add owner-extra.txt; git commit --quiet -m 'owner change'
        $refused=$false
        try { Get-AttentionRollbackCommits $saved $repo | Out-Null } catch { $refused=$true }
        if (!$refused) { throw 'Unrelated owner commit must block rollback.' }
        Write-Host '4 actual Git receipt/crash/refusal scenarios passed.'
    } finally { Pop-Location }
} finally { Remove-Item -LiteralPath $root -Recurse -Force }
