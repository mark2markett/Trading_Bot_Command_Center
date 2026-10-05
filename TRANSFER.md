# Closed-loop bundle transfer

This branch contains the validated testing branch bundle and its reports/screenshots. It does not replace GitHub main or change the checked-out Windows production branch.

Original local base: feat/options-m7 at 2783f2eae2657a9d60b37f4ac5053715633ed683. Delivered test/closed-loop head: b7c7055fc43835adca8b3cc1106947909232eb7c. The incremental bundle requires that base.

Verification: 151 Python tests, 5 web tests and web build passed. Harness runs matched 33 PASS / 1 FAIL / 7 NOT COVERED. Existing two-leg spread Flatten button defect remains reported; API flatten passed. Windows live state and real data were not verified in cloud.

On the Windows machine, use a unique temp folder to retrieve this transfer branch, then verify/import the bundle from the original command-center repo:

```powershell
$transfer = Join-Path $env:TEMP ('cc-transfer-' + [guid]::NewGuid().ToString('N'))
git clone --depth 1 --single-branch --branch transfer/closed-loop-bundle https://github.com/mark2markett/Trading_Bot_Command_Center.git $transfer
Set-Location C:\Users\Administrator\trading_bots\command-center
git bundle verify (Join-Path $transfer 'command-center-closed-loop.bundle')
git fetch (Join-Path $transfer 'command-center-closed-loop.bundle') 'test/closed-loop:test/closed-loop'
```

Fetching leaves the production branch checked out. The ZIP contains the complete handoff, reports/screenshots and checksums.
