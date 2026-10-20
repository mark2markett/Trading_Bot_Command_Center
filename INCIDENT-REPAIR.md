# Incident monitor repair

This package repairs four monitoring defects without changing bot strategies,
orders, holdings, risk limits, entry pauses, or scheduler configuration:

- Current shared-account valuation evidence can recover an earlier session's
  open valuation incident. Two distinct advancing healthy checks are required.
- An intervening failure resets recovery progress, including older open cases.
- Successful readiness reads recover a prior local API-read failure.
- Failed bot runs have an explicit classification. Existing unknown incidents
  are explained from structured source kinds while preserving IDs and history.

Historical failed runs remain for review. A successful next-day scanner cannot
erase an earlier missed SIP opening. The installer never acknowledges alerts,
retries orders, releases pauses, or replays a missed opening.

Run `INSTALL-INCIDENT-REPAIR.ps1 -Repo <command-center-path>` from this downloaded
package. It validates the reviewed source, runs a real cross-session recovery
probe against a disposable database, and prints a backup receipt. It temporarily
disables the monitor, waits for its current check, restarts only the owned server,
verifies source and API readback, then restores the monitor's enabled state.
Installation errors attempt source rollback. Unverified restoration leaves
automatic monitoring disabled and reports the recovery receipt.

The existing position observer runs every 30 seconds; the incident task runs
every minute. After installation, allow two successful minute checks for a
recovered valuation alert to resolve. A stale valuation remains an open incident.

Scope limits: local passing tests do not verify Windows installation, live data
entitlements, notification delivery, or the next session's SIP publication.
Paper fills in the existing application are local simulations, not orders inside
a Schwab paper account. Broker-side paper execution remains blocked pending a
verified supported Schwab interface. Live execution is not enabled by this repair.
