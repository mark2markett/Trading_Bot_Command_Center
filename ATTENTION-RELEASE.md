# Automatic attention handling — October 15

The October 16 update adds observation-only expiration/volatility context and descriptive research cohorts.
See [EXPIRATION-CONTEXT-RELEASE.md](EXPIRATION-CONTEXT-RELEASE.md) for its scope and installation checks. The current
bundle uses branch `fix/paused-sip-observation-20261016` and includes the preceding complete reliability release.
See PAUSED-SIP-REPAIR.md for the pause/scanner defect and a separate display-only update that can run with an open holding.

The October 15 reliability update also validates account book marks, retains redacted quote provenance,
settles new daily paper fills/fees idempotently, shows the fleet entry pause and simulated-stop semantics,
and includes a read-only SPY reconciliation audit plus isolated research gates. Existing financial history
is retained; no control or strategy parameter is reset. A previous fully installed attention version is a
recognized upgrade base; unknown/partial source still requires its receipt-based recovery.

Rollback to older accounting source is refused after fee-bearing history or cost allocations exist. Keep
the current ledger and use a reviewed forward-compatible fix; never restore an old financial database.
The strict flat/idle installation guard remains. An open SPY holding must not be closed just to install.
Windows execution, actual notification receipt, current broker/SPCX evidence and future clean sessions
remain operator verification steps; cloud tests alone cannot certify live trading readiness.

This release adds one-minute incident handling to the existing Windows monitor and dashboard. Unknown issues
receive a recorded request for review and sanitized evidence. The only repair is starting the exact enabled,
stopped Command Center server task; its persisted cooldown is 30 minutes. Bots, orders, risk controls, capital,
and scanner deadlines are unchanged. Acknowledgment does not resolve an issue.

Run after bot commands finish, after 16:15 ET or before 09:20 ET. This accounting update refuses all open positions
and unresolved orders, including a normal pending daily SPY paper BUY MOC. It does not cancel or settle orders.
It stages the native tests before installation, preserves unrelated owner files, backs up state consistently,
records rollback metadata before mutation, installs an observation-only worker first, and enables limited recovery
only after two coherent observations if `-Activate` is supplied. The current Windows account must remain signed
in if its task uses interactive logon.

```powershell
& {
    $ErrorActionPreference = 'Stop'
    $attentionRelease = Join-Path $env:TEMP ('cc-attention-' + [guid]::NewGuid().ToString('N'))
    git clone --depth 1 --single-branch --branch transfer/sip-scanner `
        https://github.com/mark2markett/Trading_Bot_Command_Center.git $attentionRelease
    if ($LASTEXITCODE -ne 0) { throw 'Download failed.' }
    powershell.exe -NoProfile -ExecutionPolicy Bypass `
        -File (Join-Path $attentionRelease 'INSTALL-ATTENTION-HANDLING.ps1') -Activate
    if ($LASTEXITCODE -ne 0) { throw 'Installation or activation needs attention; preserve the printed receipt and output.' }
}
```

Expected: staged tests pass; a recovery receipt path is printed before source changes; one-minute observation
installation succeeds; limited server recovery and configured notification routing are enabled. No test message
is sent. `/api/incidents` and Needs attention show monitor freshness, unresolved cases, recovery history, and
notification-channel status. Without an already configured SMS/email channel, external notifications remain
unconfigured and local status says so. This cloud chat does not receive continuous reports automatically.

Keep the printed receipt directory. If rollback is needed, invoke this release's installer with
`-Rollback -Receipt '<printed directory>'` under the same idle/state guards. It supports exact known partial source
stages and an owned enabled stopped server. It refuses conflicting Git operations, unrelated subsequent commits,
unknown source or runtime changes. Incident history is retained; financial backups are never restored over the
live ledger. A conflicting cherry-pick needs investigation; do not reset or discard owner changes.

Cloud verification covers real Python/React code, canonical staged source with Windows Git line-ending defaults,
fake Windows task adapters, actual Git source/receipt crash recovery and source rollback, plus browser layouts.
A real Windows Task Scheduler installation/rollback and configured notification delivery remain owner-side
verification. The installer provides those concrete checks; tests alone do not establish installed monitoring or
successful live scanner publication.
