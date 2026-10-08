# Dashboard repair

Source commit: ff9a16f937d960fbc41cc21ea0ee6dfadd19b104, based on the previously delivered SDK/server repairs through 54390e0. The bundle requires the original native 2783f2e commit; only the seven-file dashboard commit is cherry-picked into native feat/options-m7.

- Fleet and Journal alerts wrap long URLs inside their cards; acknowledgement buttons remain visible.
- Heartbeat labels, Day P&L headings and Open links stay together.
- Fleet-health counts wrap inside small phone tiles.
- Today's schedule uses the latest heartbeat for each run on the Eastern calendar day, with reported OK, failed and not-reported labels. An earlier success no longer hides a later failure. These are heartbeat reports, not claims that a full trading session completed.

Verified: all 239 Python tests, all 11 frontend unit tests, 11 Chromium regression checks (Fleet/Journal at 1440, 1024 and 390 pixels, schedule labels, acknowledgement and phone health tile), TypeScript and production build. Scoped Python lint and Git whitespace checks pass. Frontend lint exits successfully with three existing warnings in unchanged App.tsx/ui.tsx; Python reports the existing Starlette/httpx test-client deprecation warning.

Run APPLY-DASHBOARD-FIX.ps1 in Windows PowerShell. It verifies payload and built-asset SHA256 hashes, preserves unrelated working-tree changes, tests the schedule against a temporary ledger, backs up the existing dist directory, installs the prebuilt dashboard and restarts only CC server. No npm installation is required. It checks server health, the new schedule response and the served build asset identities. Native execution and the final rendered Windows page still require this installation; cloud tests are not native installation evidence.

The screenshot's unacknowledged alerts are retained. The current session recovery code already retries transient Schwab HTTP 500 history failures. SIP's earlier failed heartbeat remains recorded; the newly configured scanner still needs the scheduled morning live check. This dashboard repair changes no trading rules, feeds, credentials, controls, capital or task settings.
