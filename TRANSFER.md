# Closed-loop bundle transfer

Delivered test/closed-loop head: d89ceab8150be8ed32dcf32edf0141daebd245a7. Original required local base: feat/options-m7 at 2783f2eae2657a9d60b37f4ac5053715633ed683. GitHub main is unchanged.

This update fixes the reported two-leg spread Flatten button: enabled for any nonzero open positions, disabled when flat. Existing confirmation/API flow is preserved. Five new component regressions bring the full web suite to 10 passing tests; production build and lint pass. Complete cloud browser harness: 34 PASS / 0 FAIL / 7 NOT COVERED, exit 0. Python unchanged since the verified 157-pass launcher correction.

Mark verified the Windows launcher correction in 33281cd: browser-enabled run 38 PASS / 1 FAIL / 2 NOT COVERED. The sole failure was the spread button fixed here. Live fingerprints matched, cleanup passed and feat/options-m7 was restored. Schwab and scheduled/live/scanner integrations remain uncovered. This latest UI fix requires a local rebuild and harness rerun.

Retrieve this branch into a unique temp folder and import the bundle from the original command-center repo:

```powershell
$transfer = Join-Path $env:TEMP ('cc-transfer-' + [guid]::NewGuid().ToString('N'))
git clone --depth 1 --single-branch --branch transfer/closed-loop-bundle https://github.com/mark2markett/Trading_Bot_Command_Center.git $transfer
Set-Location C:\Users\Administrator\trading_bots\command-center
$bundle = Join-Path $transfer 'command-center-closed-loop.bundle'
git bundle verify $bundle
git -c gc.auto=0 fetch $bundle 'test/closed-loop:test/closed-loop'
```

Fetch preserves the current branch and working files. Temporarily select test/closed-loop, run npm run build in cc_web, then run .venv\Scripts\python.exe scripts\closed_loop.py. Restore feat/options-m7 in a finally block. Disabling automatic Git housekeeping for the fetch avoids the unrelated Windows locked-pack cleanup prompts without deleting any files. The ZIP contains complete evidence, handoff and checksums.
