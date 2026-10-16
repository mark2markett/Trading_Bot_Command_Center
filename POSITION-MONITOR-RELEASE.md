# Position checks every 30 seconds — October 16

The runtime now observes ledger positions every 30 seconds in a separate background loop. It runs even with no
dashboard open, and independently of the existing risk loop's provider requests. Each start accounts for work time;
four seconds of work leaves 26 seconds until the next start, rather than extending the interval to 34 seconds.
The existing risk loop and its account-quote requests remain on their existing 15-second schedule.

The observer reuses available account marks and checks their actual timestamps, invalidation state and recorded
stops. It creates a review alert on stale/missing quotes, missing/mismatched stop records or a crossed stop level.
Repeated observations of the same issue do not generate another alert on every tick. A background failure cannot
manufacture freshness: checks older than 60 seconds show overdue. Closed-market quote age is identified separately.
Provider failure or a suspended computer can prevent current observations; neither is presented as a current check.

On the bot detail page, **Last position check** and quote age are separate from **Strategy run** and **Signal schedule**.
The page refreshes every 15 seconds, including while the tab is in the background, and ages check status locally
even if API updates stop. Marked P&L is shown only with a fresh observation/quote. The old daily signal price is no
longer presented as current unrealized P&L. A legacy backend shows **Position checks unavailable**.

These are ledger observations, not broker reconciliation or continuous stop execution. The SPY daily-paper stop
is explicitly labeled **Simulated daily-bar stop**, evaluated during reconciliation. No strategy run, order, fill,
position, control flag, schedule, stop threshold or capital is changed by the observer. Daily signals remain at
15:50 ET and reconciliation at 09:45 ET. A crossed simulated stop produces a review alert, not an intraday fill.

## Install and verify

The full runtime package includes all preceding repairs. The existing flat-account, resolved-orders, idle-command
and maintenance-window guards remain: before 09:20 ET or after 16:15 ET. Do not close an open position merely to
install. Existing financial records and risk pauses are preserved. Previous complete releases are recognized.

```powershell
& {
    $ErrorActionPreference = 'Stop'
    $release = Join-Path $env:TEMP ('cc-position-monitor-' + [guid]::NewGuid().ToString('N'))
    git clone --depth 1 --single-branch --branch transfer/sip-scanner `
        https://github.com/mark2markett/Trading_Bot_Command_Center.git $release
    if ($LASTEXITCODE -ne 0) { throw 'Download failed.' }
    powershell.exe -NoProfile -ExecutionPolicy Bypass `
        -File (Join-Path $release 'INSTALL-ATTENTION-HANDLING.ps1') -Activate
    if ($LASTEXITCODE -ne 0) { throw 'Installation needs attention; preserve the receipt and paste the output.' }
    Invoke-RestMethod http://127.0.0.1:8585/api/bots/spy_mr -TimeoutSec 10 |
        Select-Object -ExpandProperty position_monitor | ConvertTo-Json -Depth 6
}
```

Refresh with Ctrl+F5. Verify the actual `checked_at` advances approximately every 30 seconds on Windows. Flat positions
need no quote. An open position also needs a timestamped current quote and appropriate recorded stop; a recent check
alone cannot prove those passed. The observer itself makes no extra provider calls and does not send notifications.
Existing configured incident/notification handling receives its review alerts; actual external delivery remains a
separate verification. See ATTENTION-RELEASE.md for recovery receipts and installation constraints.

The display-only update in PAUSED-SIP-REPAIR.md can show the corrected labels while a holding remains open, but it
does not install this runtime observer. Cloud checks do not establish installed Windows monitoring or trading readiness.
