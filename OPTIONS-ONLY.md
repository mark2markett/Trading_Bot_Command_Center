# Options-only entries

The October 20 correction enforces the owner's options-only requirement for new entries.
Only `gap_go_spread` currently implements an options strategy. The other four registered
strategies (`spy_mr`, `gap_go`, `nr7`, `sip_orb`) trade stocks and are paused for entries.
They have not been converted into option strategies. Existing holdings, exit logic,
working stops and historical trades remain visible and keep their original quantities.

Run `ENFORCE-OPTIONS-ONLY.ps1 -Repo <native checkout>` from the published transfer branch.
It verifies checksums, binds to the selected running API ledger and requires exactly the
five registered paper bots. It records a receipt under `var/backups/options-only-*` and:

1. Uses the existing audited API to pause stock strategies before installing source.
   Existing pause files retain their contents, including SIP's four-loss reason and any
   independent options-bot pause. Active stock processes can still manage existing exits.
2. Invokes the guarded runtime installer, which backs up source and the dashboard, uses
   the maintenance lock, and restarts only the owned server. It preserves Task Scheduler
   actions and schedules. Failed application attempts restore the previous source.
3. Verifies the reviewed SDK/API source is installed and no non-option opening order is
   already pending. It records an audit before exclusively creating `var/control/OPTIONS_ONLY`.
   Activation writes only the `controls` audit and the restrictive flag; it cannot modify
   positions, orders, fills, limits or trade history. Existing share openings require review;
   the installer does not fabricate cancellations.
4. Verifies the active API policy, stock entry restrictions and original control hashes.
   Any failure retains restrictive stock pauses and prints the receipt.

The SDK rejects new stock/futures entries even if a stock symbol is given an options
multiplier or instrument label. Valid OCC option-opening sides still require all existing
quote-age, size, premium, exposure and loss checks. A risk-reducing label is accepted only for a closing side and quantity that reduces the recorded holding without reversing it. Aggregate closing legs cannot collectively reverse a holding. Genuine risk-reducing exits remain permitted. Stock and options SDK runners stop on an exit refusal, retain holdings/in-memory state and report `EXIT_BLOCKED`; they do not record a fill after rejection.
The API refuses Resume for the four stock strategies while the options-only flag exists.
A generic rearm does not remove this restriction. The overview explains options-only
entries and explicitly identifies inherited share holdings retained for exit management.

The installer does not liquidate or convert SPY, resume an options bot, remove a kill/risk
pause, increase limits, replace a stock strategy with a newly invented option strategy,
change market-data sources, or enable live trading. Paper fills remain local simulations;
this change does not create Schwab paperMoney API execution. Provider permissions and
freshness still require runtime verification. Owner Windows installation is confirmed only
from the actual printed verification result.

Tests cover order-level rejection/bypass attempts, valid option entries, preserved exits,
Resume refusal, API/reporting, audit-before-flag, SQL-trigger write refusal, idempotent
activation, unknown/working opening orders, source/ledger mismatch, partial pause failure,
PowerShell boundary order, actual HTTP activation and desktop/mobile rendering.
