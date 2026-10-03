# Acceptance Tests

Operator-run checks at the end of the build. Each is pass/fail. The build is not done until every row passes.

| # | Scenario | Steps | Pass when |
|---|---|---|---|
| A1 | Cold start | Fresh clone → README install → `make dev` | Dashboard loads at 127.0.0.1:8585 in < 1 s with "no bots yet" state, no console errors. |
| A2 | Seeded fleet | `python scripts/seed_demo.py` → reload | 5 bots visible, sorted degraded-first; tiles populated; correlation matrix shows one pair ≥ .7 with a warning sentence. |
| A3 | Real bot joins | Run `bots/spy_mr_bot/bot.py reconcile` in paper mode | SPY Daily MR appears with heartbeat time, FLAT, signal values matching `bot.py check` output. |
| A4 | Rules untouched | `git diff` on `bots/spy_mr_bot/strategy.py` vs pre-build tag; replay test | Diff empty; replay test passes. |
| A5 | Fat-finger rejected | Template bot attempts order 3× max size | No broker call (mock asserts), `orders.status='rejected'`, visible in bot Decision log and Needs attention within 15 s. |
| A6 | Kill drill | Click KILL ALL → type word → confirm | `var/control/KILL` written, audit row first, all paper positions flattened on next reconcile, header shows KILLED · re-arm, page alert sent to console adapter. < 5 s. |
| A7 | Re-arm | Click Re-arm, add note | KILL file removed, audit row, bots resume on next run. |
| A8 | Pause keeps exits | Pause new entries → bot with position hits exit rule | Exit order allowed; new entry on another bot rejected with reason "paused". |
| A9 | Silence is failure | Stop a live-mode bot's scheduled task; wait 11 min (or mock clock) | Row turns degraded, heartbeat cell reads "missed N min", page alert raised. |
| A10 | Drawdown ladder | Seed broker equity series crossing −6 % then −8 % | At −6 % PAUSE_ENTRIES written + audit; at −8 % flatten flags on the two most correlated bots + audit. |
| A11 | Parity drift | Seed 12 trades with 7 losses on a bot whose backtest win rate is 73 % | Verdict ⚠ "win rate 42% vs 73%", attention item, digest alert (paper) / page alert (live). |
| A12 | Limit edit audited | Change daily loss limit on Risk page with a note | Audit log shows actor, before → after, note; new value enforced by SDK on next pre_trade. |
| A13 | Token warning | Set token file mtime to 6 days ago | Header chip turns ⚠ "token 1d left"; at < 2 days a page alert fires once, not every tick. |
| A14 | Early close | Set system date to day before an early close | Attention item "Early close … decide run moved to 12:50"; scheduler task time updated. |
| A15 | Server down, bot safe | Stop server; run bot decide with an oversized order | Rejected locally by SDK; heartbeat and rejection appear in UI once server restarts. |
| A16 | Phone | Open on a 390 px viewport | Bottom tab bar, KILL ALL full width, bot cards readable, all buttons ≥ 44 px. |
| A17 | Accessibility | Keyboard only | Tab reaches KILL ALL, modal, confirm; screen reader reads mode badges and verdicts; axe reports 0 serious issues. |
| A18 | No secrets | `git grep -i -E "secret|token|api_key"` on tracked files | Only variable names and docs; no values. `var/` and `.env` untracked. |
