# Trading overview rebuild

The home page answers: what is held, which positions are gaining or losing, which bots are paused or have failed reports, and what needs attention. It refreshes every 15 seconds. The installed activity backend remains unchanged.

## What is visible

- Account balance, today's account-value change with its reference balance, realized P&L on trades closed today, and the overall recorded trade result. Each period is labeled separately.
- Open position cards: direction, quantity, entry/current price, signed position value, profit/loss in dollars and percent, price age, owning bot, option expiry, individual option legs, and matching recorded stops. Stale prices are unavailable; short liabilities retain negative values but per-unit quote prices remain positive.
- Bot cards on both Overview and Bots: holding/flat, entry permission, pause reason, failed or missing current-session report, latest run time, working/unverified order counts, and open/closed P&L. A healthy report is not proof of a continuously running process or verified broker protection.
- Separate working-order, closed-trade and order-history tabs. Entry/exit trade prices and recent recorded fills distinguish requested order prices from executions. Order rejection reasons remain visible. All-history P&L is not limited to the current page.
- Needs attention near the holdings, current exposure and limits, drawdown, fleet control state, next or missing scheduled report, and expandable schedule/correlation details. Existing token/market indicators remain available.
- Bot detail uses the same fresh holdings/financial components; historical signals, research and risk diagnostics are available in an expandable section. Trades & orders replaces the old journal landing page, retaining alert history below it.

Paper trading and simulated daily-bar SPY stops are labeled explicitly. Historical data gaps (for example missing trade symbols or commissions) are not guessed. Today's labels require the current Eastern session, including across midnight. Existing scanner failures and retained risk pauses are not hidden or cleared.

## Display-only activation

Run `APPLY-TRADING-OVERVIEW.ps1 -Repo <native checkout>` from the published transfer package, then press Ctrl+F5. It requires the previously installed activity API, verifies the running ledger identity, payload hashes and source compatibility, and uses the shared maintenance lock. It writes only compiled static assets and the index; no server restart, task changes, native trading-source changes, control changes, or financial database writes occur. Receipts and prior index are saved under `var/backups/activity-dashboard-*`; failed served-content verification restores the prior index. Prior hashed assets remain available to open browser tabs.

The older full `INSTALL-ACTIVITY-DASHBOARD.ps1` remains available for compatible paper installations needing the activity backend itself. The display-only activator refuses a missing or changed activity backend instead of installing source during market operation.

## Verification

The complete frontend test suite and TypeScript/production build pass. Tests include period reconciliation, stale marks, Eastern midnight, short share/option prices, profit/loss filtering, unknown order states and pagination. Chromium checks cover desktop/mobile layouts, overview-to-bot-to-history navigation, filters and history tabs without trading requests. Installer tests verify source/ledger/control preservation, API compatibility refusal, recovery, and PowerShell argument handling with spaces. PowerShell tests use mocked task APIs in PowerShell 7; actual owner-machine activation still requires its installer output.
