# Fleet reliability repair — October 15

Native source: `fix/fleet-reliability-20261015` in the checksummed attention bundle.
Platform source: https://github.com/mark2markett/m2m-platform/pull/1309 (owner merge and deployed SHA verification required).

The release validates account quote books and stores redacted provenance, makes new SPY paper settlements
idempotent and cost-inclusive, prevents retries from applying pre-entry daily prices to a new stop, recovers
durable simulator submissions after state-write crashes, and prevents exhausted alerts from hiding newer
risk pages. Fleet pauses and simulated daily-bar stops are labeled explicitly. Research is isolated, its
baselines/hypotheses are frozen, and missing licensed data produces INCONCLUSIVE rather than invented results.

Verification: 358 native tests, 17 dashboard unit tests, two phone/desktop browser checks and dashboard build;
136 transfer tests and cloud PowerShell receipt/ownership/task scenarios. Platform: 9,963 passed, 1 expected
failure, 14 skipped, 11 TODOs; type checks and affected quality gates passed. Local inventory scans required a
30-second timeout; CI configuration/assertions were not changed. Actual Windows and provider tests remain due.

Installation requires flat positions, no unresolved orders and idle bot commands in the supported maintenance
window. The guard will refuse a pending daily order because this release changes settlement code. Do not close
a holding, cancel an order or clear a pause merely to install. Unknown source and partial upgrades also stop.
Only the exact previous complete attention version is accepted as an upgrade base. Retain the printed receipt.

Use the existing `INSTALL-ATTENTION-HANDLING.ps1` after those prerequisites hold. It stages the canonical
native test suite before source changes, takes consistent backups, preserves owner files, installs observation
mode, and permits already approved limited recovery only after two coherent observations with `-Activate`.
Fee-bearing financial history blocks rollback to older accounting code; use a reviewed forward-compatible
repair. Never restore an old financial ledger.

Before installation, the standalone audit can inspect existing records without changing source or runtime:

```powershell
$ccRepo = 'C:\Users\Administrator\trading_bots\command-center'
# $release is this downloaded tools directory; --repo is required for this standalone copy.
& (Join-Path $ccRepo '.venv\Scripts\python.exe') -B `
    (Join-Path $release 'AUDIT-SPY-PAPER.py') --repo $ccRepo
```

Exit 2 means a discrepancy or missing evidence, not an attempted correction. Keep output private and collect
a fresh `COLLECT-CC-REVIEW.ps1` bundle. Historical fill/cost correction still needs actual current state and
event evidence; this update never rewrites old records or initial capital.

Still required: real owner-visible notification receipt; Windows lock/task/recovery checks; authenticated
current-session SIP publication and native consumption; verified SPCX provider/history evidence; five clean
openings/closes; licensed point-in-time strategy inputs and at least twenty future clean paper sessions.
The 09:36 cold-publication target is constrained by existing REST pacing, and is not claimed fixed. Native
consumption retains its 09:40 deadline. The incomplete-stock exception is not extended beyond October 16.
No control, loss guard or strategy parameter is reset. This package is not a live trading readiness certificate.
