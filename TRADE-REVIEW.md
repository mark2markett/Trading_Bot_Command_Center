# Options lifecycle evidence and daily review

This release extends the owner-verified a07af9d operational overlay (native
0238d94). It preserves the options-only restriction, stock strategy pauses,
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


Release validation: native source 04823ab; 436 backend tests, 52 frontend tests,
production build, targeted Ruff checks and Chromium desktop/phone checks pass.
The transfer package passes 240 Python tests including launching the actual
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
