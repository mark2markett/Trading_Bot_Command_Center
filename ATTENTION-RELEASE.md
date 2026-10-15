# Automatic attention handling — October 15

This release adds one-minute incident handling to the existing Windows monitor and dashboard. Unknown issues
receive a recorded request for review and sanitized evidence. The only repair is starting the exact enabled,
stopped Command Center server task; its persisted cooldown is 30 minutes. Bots, orders, risk controls, capital,
and scanner deadlines are unchanged. Acknowledgment does not resolve an issue.

Run after bot commands finish, after 16:15 ET or before 09:20 ET. The installer refuses open positions or unresolved
orders except the already verified normal pending daily SPY paper BUY MOC. It does not cancel/settle that order.
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
