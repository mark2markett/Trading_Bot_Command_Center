# Retire the orphaned stop after a completed local paper sale

Owner evidence: SPY is flat after the October 21 09:46 reconciliation. Native
trade 11 records SELL130 at 769.05 for October 20, entry 769.60 on October 14,
recorded P&L -71.50. Exit order 29 has fill 24; entry order 11 has fill 19. The
only remaining working SPY order is stale paper STOP21 for 130 shares at731.12.

RECONCILE-CLOSED-PAPER-STOP.ps1 uses the reviewed SPY idle/action ownership guard
and shared maintenance lock. Other session bots continue; no source, server,
schedule or control flag is changed. It invokes the explicit closed-position
mode of PAPER-EXIT-STATE.py, distinct from the older open/pending-exit correction.

Preflight requires five paper bots, all four share pauses and OPTIONS_ONLY,
matching API ledger identity, saved state flat with no pending/stop reference,
zero paper/native holdings, no queued paper orders, and no SPY simulator stop.
Exactly one active native paper STOP must remain, with no recorded stop fill.
The latest paper sale must match a completed native MOC by ID, symbol, quantity
and session. Full native entry/exit fills must agree with the closed trade and
its recorded P&L. Ambiguous or changed evidence refuses without modifying it.

A BEGIN IMMEDIATE transaction allows only the stop's status/reason update and one
receipt-linked controls audit insertion. The complete captured tables and paper
file/flag hashes are checked before commit; unexpected writes roll back. Closed
mode never rewrites either paper JSON file. Fills, trades, P&L, cash, positions,
limits and all other orders remain unchanged. Receipt apply is idempotent; keep
the printed recovery receipt. Re-running a fresh prepare after success will
refuse because no orphaned active stop remains; verify against the saved receipt.

The output distinguishes the native recorded exit price from the simulator's
actual fill price. The existing simulator applies separate slippage/charges;
this metadata correction does not silently reprice a completed trade or claim
that recorded native P&L includes every simulator charge. A price discrepancy
requires separate accounting reconciliation. All records here are local paper
simulation, not verified Schwab-side executions. Nothing enables live trading.

The full shared runtime/dashboard installation remains deferred while intraday
commands are running. Retiring this ledger record is not a broker cancel request.

Release validation: 281 transfer-package Python tests pass, including 32 pending
and closed-stop state/transaction tests. PowerShell on Linux passes five closed
wrapper cases, six pending wrapper cases, ten SPY idle/ownership/scheduling cases
and five source-wrapper cases. Independent review found no Critical/Important
issues; entry and native exit session-date checks include regression coverage.
The suite emits one existing Starlette/httpx deprecation warning. Owner Windows
activation and its recovery receipt still require verification.
