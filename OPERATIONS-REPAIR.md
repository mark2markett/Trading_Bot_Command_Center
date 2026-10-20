# Responsive API and current operational status

October 20 repair for the already installed, options-only five-bot paper fleet.
The owner reported all local API routes timing out, a monitor `DEADLINE`, and a tall
alert column hiding the bot controls. Market-data requests were still succeeding.

Reproduced defects and correction:

- GET requests could occupy the request worker pool while waiting on the singleton
  writer's ledger mutex. Each API GET now receives an independent read-only connection
  closed at request completion. No schema initialization or repair occurs on that path.
  Background risk checks and control POSTs retain their existing writable connections.
- Network dependencies shared one monitor deadline; slow platform reads could consume
  the entire tick and starve local readiness observations. Each dependency now has an
  eight-second budget within the existing 45-second tick. Failures remain visible.
- Position warnings were sticky review cases. The incident worker now consumes the
  existing thirty-second position reports read-only. Two advancing healthy checks after
  the latest failing/unknown sample can resolve recovered warnings. A stale report,
  changed holding identity, missing quote or earlier checked timestamp cannot certify
  recovery. No quote or order is fabricated, and no historical failed run is erased.
- The positions/alerts grid placed all bot cards below the full incident column.
  Positions, bot cards and orders now share an independent left workspace. The incident
  list is scrollable, current page-level issues are prioritized, acknowledged review
  history and entry checks for policy-paused flat stock bots are grouped explicitly.
  Counts distinguish currently shown issues from retained, unresolved history. Position
  evidence names stale quotes and missing/mismatched stops; it does not assert a broker
  position mismatch without evidence. Browser API requests abort after eight seconds.

## Apply once

Run `REPAIR-OPERATIONS.ps1 -Repo <native checkout>` from the published transfer branch.
It verifies checksums and performs an offline read-only preflight: exact five paper
registrations, active OPTIONS_ONLY flag and all four stock entry pauses. It records
control hashes and financial observations under `var/backups/operations-repair-*`.

If the local API is unresponsive, it verifies the existing server and monitor task
ownership, pauses the monitor, waits for its current tick, and restarts only the owned
server after both task Ready and listener closure. It restores the prior enabled monitor.
No arbitrary PID is killed; an unexpected task or occupied port blocks recovery.

The script invokes the existing guarded options-only installer, which binds the running
API ledger, verifies source compatibility, backs up source and dashboard, uses the shared
maintenance lock and restarts the server for the reviewed overlay. It retains positions,
orders, options-only restriction, SIP loss pause, limits and bot task schedules. It then
waits for any overlapping monitor tick to finish, starts a new owned check, and separately
budgets its completion. The final check requires a completion timestamp after that boundary
and verifies original control hashes. A failure prints a receipt and retains restrictions;
it never resets financial history or claims that all incidents are resolved.

Current provider freshness and owner-machine Task Scheduler behavior still require the
printed runtime verification. Schwab authorization warnings need the account owner's
reauthorization; no token/credential is collected by this repair. Paper execution remains
local simulation; this release does not supply a Schwab paperMoney execution API or live
trading authorization. Stock strategies are not converted into options strategies.

## Validation

Native regression suite, frontend suite/build, actual packaged HTTP activation, offline
preservation tests, desktop/phone Chromium geometry with eleven incidents, and PowerShell
success/failure/overlapping-monitor scenarios are checked before publication. Real provider
requests and production trading orders are not part of those synthetic tests.
