# Command Center transfer

Delivered test/closed-loop head: b220dbda4f3bc58d003d5bc110f519e57cd02e5c. Required original base: feat/options-m7 at 2783f2eae2657a9d60b37f4ac5053715633ed683. GitHub main is unchanged.

Latest isolated fix b220dbd addresses shared SQLite connection races that stalled the Windows server. The exact SQLite API misuse was reproduced in concurrent real endpoints/risk ticks. Ledger operations now serialize execute/fetch/lastrowid/cursor close and existing migration; riskd records tracebacks. No risk settings, trading rules or stored data are reset. 161 full Python tests pass, four focused regressions pass, lint passes, independent review has no Critical/Important production findings. Complete cloud browser harness: 34 PASS / 0 FAIL / 7 NOT COVERED. Web remains at the previously verified 10 tests/build.

The preceding UI fix was confirmed on Windows: 39 PASS / 0 FAIL / 2 NOT COVERED, exit 0. Schwab and scheduled/live/scanner integration gaps remain. The Monday server recovery is now pending local application/restart.

Retrieve into a unique temporary folder and verify/import from the original command-center repository:

```powershell
$transfer = Join-Path $env:TEMP ('cc-transfer-' + [guid]::NewGuid().ToString('N'))
git clone --depth 1 --single-branch --branch transfer/closed-loop-bundle https://github.com/mark2markett/Trading_Bot_Command_Center.git $transfer
Set-Location C:\Users\Administrator\trading_bots\command-center
$bundle = Join-Path $transfer 'command-center-closed-loop.bundle'
git bundle verify $bundle
git -c gc.auto=0 fetch $bundle 'test/closed-loop:test/closed-loop'
```

For the urgent server recovery, preserve logs and a consistent SQLite snapshot, verify the stalled server's process identity before stopping it, and keep feat/options-m7 checked out. Apply only this commit:

```powershell
git cherry-pick b220dbda4f3bc58d003d5bc110f519e57cd02e5c
& .\.venv\Scripts\python.exe -u -m cc_server.main
```

Fetch and isolated cherry-pick were verified against an originless original-base fixture: production branch name, unrelated working changes and runtime sentinel preserved. Do not force conflicts or merge main. The four-file server fix is independent of harness modules and requires no web rebuild. Other bot tasks are not restarted automatically by these instructions. The ZIP contains full evidence/checksums/handoff.
