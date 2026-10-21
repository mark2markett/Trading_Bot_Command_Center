# Options lifecycle evidence and daily review

This release extends the owner-verified 7dfbfdd readiness overlay (native
3c85161). It preserves the options-only restriction, stock strategy pauses,
existing SPY holding and exit handling. No broker orders, financial migrations,
strategy changes, bot task starts/stops or risk-limit changes occur during install.

Run INSTALL-TRADE-REVIEW.ps1 only after bot commands finish and more than five
minutes before their next scheduled start. Python processes must be inspectable.
The installer refuses active commands, verifies the existing paper fleet and
options-only flags, writes recovery receipts, installs reviewed source/compiled
UI and restarts only the owned Command Center server. It verifies the review API
and a new completed incident-monitor check. No Git reset, stash or force update.

Open **Review** in the navigation or http://127.0.0.1:8585/review. Select a session
date. During the day the report is provisional. The server checks every minute
and saves JSON/Markdown to var/reviews at exchange close +30 minutes: 16:30 ET on
regular sessions, 13:30 ET on early closes. The clock follows America/New_York,
including DST, and the existing 2025–2027 exchange calendar. Startup catches up
the latest completed session. Inspect the displayed automatic review status and
saved timestamp; installation alone does not prove an after-close run occurred.

Reports contain observed trade results, session fill fees, per-bot counts,
decisions/passes, explicit new option candidate/order/fill/exit links, actual
captured bid/ask books and quote times, sizing/max-loss context, sampled option
liquidation observations, deterministic evidence-citing findings and limitations.
Old trades retain their recorded results and carry missing-link warnings.
Historical close holdings and hypothetical missed-trade profits are not invented.
Future option runs capture linked evidence; a running old process is never
silently treated as upgraded. Stock strategies remain disabled for new entries.

No parameter recommendation is applied by this native report. Existing platform
auto-calibration is a separate subsystem. Historical option counterfactuals,
complete market/universe coverage, broker reconciliation, new option strategies
and Schwab-side paper execution remain explicit unverified requirements. Local
paper IDs/fills are labeled simulations; no setting turns them into paperMoney
executions. Nothing enables live trading.


Release validation: native source includes exact-session reconciliation and pending-exit checks; 456 backend tests, 55 frontend tests,
production build, targeted Ruff checks and Chromium desktop/phone checks pass.
The transfer package passes 258 Python tests including launching the actual
bundled server and generating a saved review against an owned test ledger.
PowerShell checks cover five idle guards, four review wrapper scenarios, eight
source install/recovery scenarios, five options-policy scenarios and seven
operations scenarios. These ran in PowerShell on Linux; owner Windows activation
and the first after-close run must still be verified from their output.

Review findings addressed: operational heartbeat failures appear even without
trade decisions; candidate net P&L requires fully reconciled distinct opening and
closing spread legs and an explicit commission basis; source apply and rollback
recheck active bot commands. If a bot starts while candidate health verification
fails, source rollback is refused and the recovery receipt is preserved rather
than replacing imported SDK files. This requires operator recovery once idle.


October 20 readiness repair: explicitly options-only-disabled share strategies
skip entry-only scanner and daily context requirements while managing existing
exits first. Ordinary pauses retain scanner observation. The monitor omits SIP
opening requirements only if a dated policy proves prohibition by 09:35; later
policy changes cannot erase earlier failures. Historical incidents stay intact.
This update does not implement broker-side Schwab paper execution.

Run installation inside the original trading server session. The owner's DESKTOP
profile C:\Users\markw has no trading checkout; localhost there is a different
endpoint from the installed Administrator trading server. A failed connection on
that desktop is not evidence that the original server is down.


Pending paper session guard: the SPY daily bot must find exactly one daily bar
matching the saved pending order date before settling. Earlier or later bars
cannot supply its fill close; missing/ambiguous matches leave paper state intact.
This installs bot.py source under the same idle and exact-source compatibility
checks. state_paper.json and paper_ledger.json are never packaged, overwritten or
reconciled by this installer. It does not fill or cancel the owner's current
orders 29/21. Their saved paper queue/stop state was inspected; the separately audited stale-stop repair below applies only after a fresh matching preflight.

October 21 paper exit state repair:
The owner confirmed the simulator holds 130 SPY, has exactly one queued October
20 SELL130 MOC, and has no SPY stop. State and native order 21 still refer to the
old simulated stop. REPAIR-PAPER-EXIT-STATE.ps1 installs the session-date guard and
pending-exit display, then rechecks this evidence while bot commands are idle.
Its separately audited helper changes only the stale native stop status/reason
and saved stop_order_id; it appends one control audit record. Native position,
pending order 29, cash, paper queue, fills and flags are verified unchanged.

Ambiguous, filled, changed or live evidence refuses the metadata correction.
Both database and JSON state are checked before commit; a failed database write
rolls back and restores only its own state bytes. The recovery receipt supports
idempotent helper apply after an interrupted write. Do not manually delete the
receipt, stop files or orders. A new wrapper invocation after a completed repair
may refuse preflight because the stale stop is already retired; use the original
receipt for read-only verification rather than preparing another correction.

The dashboard says "Paper sell-at-close exit pending reconciliation" while the
holding remains open. It does not claim broker protection or settlement. Bot
reconciliation can settle only against the actual saved session bar. Installation
does not run a trading command. Schwab-side paper execution remains unestablished;
authorization renewal still requires the owner's Schwab login.

Current release validation also covers 16 real-file/SQLite paper-metadata cases, six metadata wrapper scenarios and a Chromium pending-exit desktop/phone check. The native/transfer suites each emit one existing Starlette/httpx deprecation warning; no failing tests. Independent review has no remaining Important/Critical findings. Windows activation still requires the owner to run the pinned release and return its receipt/output.
