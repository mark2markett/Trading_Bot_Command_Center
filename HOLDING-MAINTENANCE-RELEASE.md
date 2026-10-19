# October 19 opening maintenance

The installed Windows source reported a16d61d on Sunday October 18. Its server/risk monitor was running,
but the SPY mark was stale, the fleet entry pause remained, and only the static attention display
had previously been installed. An hours-old daily strategy heartbeat is separate from position monitoring.

This maintenance package installs the reviewed incident worker and 30-second position observer and repairs
read-only SIP scanner selection while entries are paused. It starts from native base dbea152 (equivalent
source to the reported Windows release); its single native commit is fe1d2e57fcbf605ef5a42ed1883c43cfdc765ecf.
It does not install the separate accounting/settlement/book-quote changes from the full reliability bundle.
Eleven unchanged SDK/schema/feed/calendar/daily-bot files are verified before mutation. Unknown source refuses.

## Installation

Run the following before 09:20 ET or after 16:15 ET, with bot commands idle. The helper accepts exactly five
paper bots, a retained fleet entry pause and either a flat account or one existing long SPY paper holding
with one matching recorded simulated stop and matching daily state/paper files. It refuses any other open
position or unresolved order. It stages 103 server/intraday tests, then restarts only the exact owned server.
A single Git cherry-pick retains unrelated owner files. Runtime checks protect all orders, fills, positions,
trades, costs, control records/flags and existing equity-history prefixes. No historical financial DB is restored.

```powershell
& {
    $ErrorActionPreference = 'Stop'
    $cc = 'C:\Users\Administrator\trading_bots\command-center'
    $repair = Join-Path $env:TEMP ('cc-opening-' + [guid]::NewGuid().ToString('N'))
    git clone --depth 1 --single-branch --branch transfer/sip-scanner `
        https://github.com/mark2markett/Trading_Bot_Command_Center.git $repair
    if ($LASTEXITCODE -ne 0) { throw 'Download failed.' }
    powershell.exe -NoProfile -ExecutionPolicy Bypass `
        -File (Join-Path $repair 'INSTALL-HOLDING-MAINTENANCE.ps1') -Repo $cc -Activate
    if ($LASTEXITCODE -ne 0) { throw 'Maintenance stopped; preserve the printed receipt and paste the output.' }
    & (Join-Path $cc '.venv\Scripts\python.exe') -B `
        (Join-Path $repair 'CHECK-OPEN-READINESS.py') --repo $cc
}
```

The final read-only report deliberately remains NOT_READY_FOR_NEW_ENTRIES while the existing risk pause,
missing valuation or unresolved position evidence is present. Exit code 2 means those readiness blockers remain;
it does not undo installation. Refresh the browser with Ctrl+F5. Confirm actual position checked_at advances
about every 30 seconds and the incident last-completed timestamp advances every minute. Interactive task logon
requires remaining signed in. Existing notification configuration is retained; no test message is sent.
A current observation does not certify current quotes, broker protection, strategy execution or profitability.

A printed receipt is saved before source changes. To revert this maintenance source and restore the previous
monitor, use this same release's INSTALL-HOLDING-MAINTENANCE.ps1 -Rollback -Receipt '<printed directory>'.
Rollback is also confined to idle maintenance hours, verifies the receipt/patch and financial preservation,
and verifies restored server health. The dashboard remains compatible with the older backend. Never reset,
stash owner changes or restore an old financial database to force installation. The full accounting installer
keeps its flat-account guard and will refuse this distinct source until a reviewed forward upgrade is supplied.

## Platform release and opening verification

PR https://github.com/mark2markett/m2m-platform/pull/1309 was integrated with current main 36bbc915 on October 18 ET;
the sole changelog conflict preserves both histories. New reviewed head: 1c7b21add0e8cbcd991806c0f6f9b77220b21089.
The main integration requires new current-head checks and independent review. Mark performs the owner merge;
never use --admin, fabricate a status or reuse old-head approvals. Production readiness still needs a READY
deployment containing the merged commit; a push or public health 200 does not establish that deployment.

Sunday stale quotes are not replaced by synthetic marks. Before the open, verify fresh account prices and
risk-monitor updates and review the recorded drawdown and SIP loss pauses. This installer never clears them.
At 09:35–09:39 ET verify authenticated current-session publish_ready and the native UNIVERSE decision. A green
public health endpoint does not prove those. The incomplete-opening exception expired October 16; strict
completeness resumes October 19. Real missing provider bars may still block SIP and require provider diagnosis;
no data is filled, deadline extended, stock silently omitted or late strategy session replayed by this package.

The existing 130-share SPY stop at 731.12 is a simulated daily-bar record evaluated at reconciliation, not
continuous broker protection. The daily SPY strategy remains 09:45 reconcile / 15:50 decide, with existing
parameters. Holding a position is not itself authority to lift an entry pause or change a stop.

## Verification

- Native complete Python suite: 329 passed; one existing Starlette deprecation warning.
- Windows-staged scope: 103 passed (SDK tests before server tests, matching normal project ordering).
- Dashboard: 21 tests passed; TypeScript and production Vite build passed.
- Real local server: 30.003-second observer interval; protected financial records and pause unchanged.
- Release gate: actual Git CRLF install/revert preserves holding, stop, owner dev file and fingerprint.
- PowerShell task ownership/idle/readiness scenarios passed under verified PowerShell 7.5.4.
- Platform full suite: 10077 passed, one expected failure, 14 skipped, 11 TODO; 223 focused tests and typecheck passed.
- Independent review found no remaining major issue. Actual Windows Task Scheduler execution, delivery through
  configured external channels and live opening evidence remain operator verification, not cloud test claims.

## Git housekeeping correction

The first Windows attempt verified/imported the bundle, then recent Git started incremental housekeeping
although gc.auto was zero. Locked pack-index files produced unlink retry prompts before staged tests,
source installation or server restart. The corrected importer uses --no-auto-maintenance plus per-command
maintenance.auto=false, gc.auto=0 and gc.autoPackLimit=0; fetch commit-graph writes are disabled. Cherry-pick
and source-only rollback also disable automatic maintenance. No global Git setting is changed and no pack
file is deleted. A real Git trace regression reproduces the old child-maintenance invocation and verifies
that the corrected import launches no housekeeping and rejects an unexpected head. Run a fresh release;
do not delete locked indexes or repeatedly answer unlink prompts.
