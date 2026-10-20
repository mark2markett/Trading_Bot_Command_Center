param([string]$Repo='C:\Users\Administrator\trading_bots\command-center')
$ErrorActionPreference='Stop'
foreach($line in Get-Content -LiteralPath (Join-Path $PSScriptRoot 'TRADE-REVIEW-SHA256.txt')){
    if($line -notmatch '^([a-f0-9]{64})\s+([A-Za-z0-9_.-]+)$'){throw 'Invalid review checksum entry.'}
    if((Get-FileHash -LiteralPath (Join-Path $PSScriptRoot $Matches[2])).Hash -ne $Matches[1]){throw 'Review checksum mismatch.'}
}
. (Join-Path $PSScriptRoot 'TRADE-REVIEW-GUARDS.ps1')
Assert-TradeReviewIdle
& (Join-Path $PSScriptRoot 'REPAIR-OPERATIONS.ps1') -Repo $Repo
if($LASTEXITCODE -ne 0){throw 'Review installation needs attention; preserve the recovery receipt.'}
$review=Invoke-RestMethod 'http://127.0.0.1:8585/api/review' -TimeoutSec 10
$index=Invoke-RestMethod 'http://127.0.0.1:8585/api/reviews' -TimeoutSec 10
if($review.schema_version -ne 1 -or $review.execution.broker_verified -ne $false){throw 'Review response identity differs.'}
@{ok=$true;scope='TRADE_LIFECYCLE_AND_DAILY_REVIEW';session_date=$review.session_date;
    candidates=$review.summary.observed_candidates;closed_trades=$review.summary.closed_trades;
    automatic_review=$index.worker;next_step='Press Ctrl+F5 and open Review. Future bot runs capture new linked evidence; historical gaps remain visible.'} | ConvertTo-Json -Depth 6
