function Get-AttentionInstallBase {
    param($Release,[string]$Source)
    $base = switch ($Source) {
        'before' { $Release.base }
        'installed' { $Release.tip }
        'upgrade_from_attention' { $Release.upgrade_base }
        'upgrade_from_fleet' { $Release.fleet_base }
        'upgrade_from_expiration' { $Release.expiration_base }
        'upgrade_from_paused_sip' { $Release.paused_sip_base }
        'upgrade_from_display_label' { $Release.display_label_base }
        default { throw 'Unknown or partial source stage; preserve the existing rollback receipt.' }
    }
    if ($base -notmatch '^[a-f0-9]{40}$') { throw 'Invalid reviewed installation base.' }
    return $base
}
function Save-AttentionReceipt {
    param([string]$Repo,[string]$Backup,[string]$Before,[string]$PendingCommit='')
    $head=(git rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0) { throw 'Cannot record current source head.' }
    $commits=@(git rev-list --reverse ($Before+'..HEAD'))
    if ($LASTEXITCODE -ne 0) { throw 'Cannot record installed source commits.' }
    $record=@{repo=$Repo;installed_head=$head;commits=$commits;native_base=$Before;pending_commit=$PendingCommit}
    $temporary=Join-Path $Backup 'receipt.tmp'
    $record | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $temporary -Encoding UTF8
    Move-Item -LiteralPath $temporary -Destination (Join-Path $Backup 'receipt.json') -Force
}
function Get-AttentionRollbackCommits {
    param($Saved,[string]$Repo)
    if ($Saved.repo -ne $Repo) { throw 'Rollback receipt belongs to another repository.' }
    $current=(git rev-parse HEAD).Trim()
    $commits=@($Saved.commits)
    if ($current -ne $Saved.installed_head) {
        if ($Saved.pending_commit -notmatch '^[a-f0-9]{40}$' -or (git rev-parse HEAD^).Trim() -ne $Saved.installed_head) { throw 'Rollback source head changed; preserve the backup.' }
        $actual=(git diff --binary HEAD^ HEAD) -join "`n"
        $expected=(git diff --binary ($Saved.pending_commit+'^') $Saved.pending_commit) -join "`n"
        if ($LASTEXITCODE -ne 0 -or $actual -cne $expected) { throw 'Unrecorded commit does not match the pending reviewed patch.' }
        $commits+=@($current)
    }
    $actual=@(git rev-list --reverse ($Saved.native_base+'..HEAD'))
    if ($LASTEXITCODE -ne 0 -or ($actual -join ',') -cne ($commits -join ',')) { throw 'Rollback history differs from the receipt.' }
    return $commits
}
