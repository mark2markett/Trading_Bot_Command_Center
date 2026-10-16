# Expiration context — October 16, 2026

New bot decisions record expiration and market observations. This is observation-only: no strategy, sizing, stop,
entry cutoff, contract selection, execution pricing or risk-control policy changes. The frozen SPY strategy stays intact.
The package includes the preceding fleet reliability and attention repairs.

## What is recorded

- New York session date, ordinary weekly calendar candidate, standard monthly and quarterly expiration, holiday shifts
  and early close. Calendar coverage is 2025–2027; other years are unknown. October 16, 2026 is standard monthly expiration.
- Actual selected option contract dates and calendar DTE, including non-Friday expirations. Calendar candidates do not
  establish a listed contract, AM/PM settlement, index/futures rules, dealer positioning or gamma exposure.
- Intraday completed-bar range, unannualized minute return RSS, prior-session ATR and already-requested underlying books.
  Selected option quotes retain book timestamp provenance. A trade timestamp does not certify a fresh bid/ask.
- IV, option volume and open interest have no independent timestamp in the current quote model and remain explicitly
  unverified for freshness. Relative volume remains unavailable without a timestamped same-time volume baseline.
- Live observations use the capture clock after existing provider calls; offline feeds use the replay clock. There are
  no extra provider requests. Daily MR gets calendar context with unavailable metrics when inputs are absent.

## Install

Wait until the account is flat, orders are resolved and bot commands are idle, in the existing maintenance window
(before 09:20 ET or after 16:15 ET). Do not close positions or cancel orders just to satisfy installation. Existing
running processes do not receive this feature automatically; today's earlier records will not be rewritten.

```powershell
& {
    $ErrorActionPreference = 'Stop'
    $release = Join-Path $env:TEMP ('cc-expiration-' + [guid]::NewGuid().ToString('N'))
    git clone --depth 1 --single-branch --branch transfer/sip-scanner `
        https://github.com/mark2markett/Trading_Bot_Command_Center.git $release
    if ($LASTEXITCODE -ne 0) { throw 'Download failed.' }
    powershell.exe -NoProfile -ExecutionPolicy Bypass `
        -File (Join-Path $release 'INSTALL-ATTENTION-HANDLING.ps1') -Activate
    if ($LASTEXITCODE -ne 0) { throw 'Installation needs attention; preserve the receipt and paste the output.' }
    powershell.exe -NoProfile -ExecutionPolicy Bypass `
        -File (Join-Path $release 'COLLECT-CC-REVIEW.ps1')
    if ($LASTEXITCODE -ne 0) { throw 'Evidence collection needs attention; paste the output.' }
}
```

The guarded installer preserves runtime and owner files, tests the staged source before mutation and prints a recovery
receipt. It recognizes both preceding complete attention/fleet releases. It does not clear trading pauses, restart bot
commands, merge a platform PR, alter capital or extend the incomplete-bar exception. The existing rollback guard still
refuses a return to old accounting after fee events. See ATTENTION-RELEASE.md for activation and recovery procedures.
As in the existing attention installation, `-Activate` requests limited server recovery only after two coherent
observations; activation failure leaves observation mode running. Actual external notification receipt still needs checking.

## Check after installation

Collect the review ZIP and inspect new `decisions.signal_json.market_context` records via the existing decisions API
or a read-only ledger query. Expect `policy=OBSERVATION_ONLY`, a New York date and explicit freshness states. Existing
decisions have no new fields until another natural scheduled decision runs. A calendar record alone does not certify
live quote quality, successful SIP publication or notification delivery.

## Strategy research

From the installed native checkout:

```powershell
.\.venv\Scripts\python.exe -m research.expiration_cohorts `
    --input C:\path\private-outcomes.json --output C:\path\new-expiration-report.json
```

Input fields: `id`, `strategy`, timezone-aware `entry_at`, `gross_pnl`, `fixed_cost`, `variable_cost`,
`embedded_variable_cost`, `initial_risk`, all in one account currency. Price P&L precedes separately reported costs.
Costs included in execution prices must not be separately deducted again; record their measured amount as embedded
cost for incremental stress. Unknown embedded cost means stress is unavailable, not zero. Do not put private trade
outcomes or licensed history in this public tools repository.

Reports compare cost-inclusive mean R and net P&L by expiration cohort, with distinct session/trade counts. They remain
descriptive and INCONCLUSIVE for promotion; they omit no-trade sessions and group overnight holdings by entry date.
Preregister sizing/cutoff hypotheses, obtain licensed timestamped histories, retain an untouched holdout and collect
20 future clean paper sessions before owner review of trading-policy changes. No superior expiration strategy is claimed.
