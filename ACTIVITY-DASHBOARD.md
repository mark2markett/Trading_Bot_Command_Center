# Fleet activity dashboard

The Fleet page refreshes every 15 seconds and separates entry permissions from run health, open positions from working orders, and filled orders from completed trades.

- Open P&L: unrealized profit/loss on actual stock and option-leg quantities, using marks at most 60 seconds old. Missing/stale prices display unavailable. A stale API snapshot also masks open P&L.
- Closed P&L: all recorded closed trades, with a separate current Eastern-session subtotal. Historical commissions may be excluded; this is labeled and is separate from today's shared-account equity change.
- Open positions: quantity, entry/current value, open P&L, quote time and option expiry. Verified matching option legs are grouped as spreads; unmatched legs stay visible.
- Working orders: actual recorded status, filled/remaining quantity, prices and reasons. Unknown statuses remain visible for review. SPY paper stops are explicitly simulated daily-bar records, not live broker orders.
- Account drawdown and gross exposure show unavailable when current account equity is unknown. Missing prices never appear as a measured 0% drawdown or 0× exposure. Existing entry checks still reject unavailable account equity.
- Closed trades and order history: separate, paginated tables; page limits do not limit P&L totals. Legacy trade rows with no symbol are labeled rather than guessed.

## Installation

Run `INSTALL-ACTIVITY-DASHBOARD.ps1 -Repo <native checkout>` from the published transfer package. It verifies payload checksums, exact compatible API/dependency source, the selected running API ledger, owned server/monitor tasks and the paper-only fleet. It uses the shared maintenance lock, waits for an in-progress incident check, restarts only the Command Center server, verifies both the activity API and served assets, then restores the monitor's prior enabled state. Bot tasks keep running. No trading database, bot source, controls, financial limits, task actions or schedules are edited.

The October 19 quote-source update also installs the reviewed `cc_server/cc_server/riskd.py`, new `account_quotes.py`, and `cc_sdk/cc_sdk/polygon_options.py`. The account monitor previously requested option marks from Schwab while the spread bot used Polygon. It now requests the exact OCC option contract from Polygon, values a valid bid/ask midpoint, and rejects missing/nonnumeric books and timestamps outside the existing 90-second freshness window. Future option timestamps are refused. Missing Polygon permission, key or quote cannot fall back to Schwab options or manufacture a current mark. Stock account marks remain on Schwab. The Polygon parser also refuses missing/nonnumeric bids instead of treating them as zero. No SDK risk/order method, strategy, capital, position, order or control is edited. Current provider freshness and entitlements still require a live-session check.

`cc_server/cc_server/api.py`, `activity.py`, the read-only `risk_reporting.py`, and the compiled dashboard files remain part of the package. The source overlay is recorded in a recovery receipt without changing the owner's Git history/index. Fleet and bot-list reads calculate parity without writing caches or alerts; the background risk monitor remains responsible for those writes. Older maintenance tools may refuse this newer overlay; preserve their source guards rather than resetting the checkout.

Backups and verification receipts are under `var/backups/activity-dashboard-*`. Failed verification restores the previous source and dashboard index. If restoration cannot be verified (for example a persistent Windows file lock), the server and automatic monitor restart remain stopped/disabled and the receipt is printed for recovery; no broad process kill or financial-state rollback is attempted. Existing hashed assets remain available to older browser tabs.

Press Ctrl+F5 after installation. This reporting update does not resolve scanner publication, resume SIP, acknowledge incidents, change strategy signals or certify a clean trading session. Current installation on Windows must be confirmed from the installer output.

## Validation

Native source commit and payload identities are in `ACTIVITY-DASHBOARD.json`; the complete source is retained in `activity-dashboard-source.bundle`. Tests cover read-only SQL, stock/option P&L, quote age and mixed time zones, partial/unknown order states, absent registrations, history pagination, preservation of shares/options/pauses, atomic recovery, task ownership and failed rollback. Production UI is also checked in Chromium at desktop and phone widths without trading requests. PowerShell wrapper tests run in PowerShell 7 with mocked Windows task APIs; actual Windows Task Scheduler behavior requires owner-machine verification.
