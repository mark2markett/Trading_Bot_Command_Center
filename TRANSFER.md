# Closed-loop bundle transfer

This branch contains the validated testing branch bundle and its reports/screenshots. It does not replace GitHub main or change the checked-out Windows production branch.

Original local base: feat/options-m7 at 2783f2eae2657a9d60b37f4ac5053715633ed683. Delivered test/closed-loop head: 33281cd27c0d1e9fc9a27eee19f5f8b36e5c152b. The incremental bundle requires that base.

Verification: 157 Python tests, 5 web tests and web build passed. Harness runs matched 33 PASS / 1 FAIL / 7 NOT COVERED. Existing two-leg spread Flatten button defect remains reported; API flatten passed. The Windows first run covered live fingerprints, real Polygon and both historical replays before failing dashboard identity. This update fixes the confirmed Windows venv redirector PID mismatch while retaining strict process identity. Safe startup diagnostics and logs now survive cleanup. Actual corrected Windows startup requires a rerun; cloud does not verify Windows live state.

On the Windows machine, use a unique temp folder to retrieve this transfer branch, then verify/import the bundle from the original command-center repo:

```powershell
$transfer = Join-Path $env:TEMP ('cc-transfer-' + [guid]::NewGuid().ToString('N'))
git clone --depth 1 --single-branch --branch transfer/closed-loop-bundle https://github.com/mark2markett/Trading_Bot_Command_Center.git $transfer
Set-Location C:\Users\Administrator\trading_bots\command-center
git bundle verify (Join-Path $transfer 'command-center-closed-loop.bundle')
git fetch (Join-Path $transfer 'command-center-closed-loop.bundle') 'test/closed-loop:test/closed-loop'
```

Fetching leaves the production branch checked out. The ZIP contains the complete handoff, reports/screenshots and checksums.
