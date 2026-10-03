# Trading Bot Command Center — Product Requirements

Version 1.0 · Owner: Mark Watson · Status: approved for build

## 1. Problem

Mark runs (or will run) several systematic trading bots on one Windows PC against one Schwab account.
Today each bot is a scheduled Python script that reports through a log file and a JSON state file.
There is no single place to answer, in under five seconds: **Is anything broken? Is anything bleeding? Can I stop it?**

## 2. Goals

1. One local web app ("Command Center") that supervises every bot, in paper or live mode, from one screen.
2. Risk controls enforced **in code, before any order leaves the machine**, following FIA automated-trading guidance: pre-trade limits, drawdown ladder with escalating automatic responses, kill switch, audit log.
3. Backtest-to-live parity visible per bot: live metrics next to the backtest's expected band, with drift flagged.
4. Silence is failure: a bot that doesn't check in is shown as broken, not as idle.
5. Zero new broker dependencies. Schwab is the only broker. The Command Center never holds broker credentials of its own; bots keep them.

## 3. Non-goals (v1)

- No strategy builder, no backtesting engine in the UI (TradingView and Python notebooks remain the research tools).
- No multi-user auth. Localhost + optional Tailscale for phone access. One operator.
- No cloud deployment. Runs on the trading PC.
- No crypto, no futures. Equities and equity options at Schwab only.
- No order entry by hand from the UI. The UI can only pause, flatten, kill, re-arm and re-run a bot's scheduled command.

## 4. Users

One: the operator. Experienced in market data and options; comfortable reading a log; wants plain language, no consultant-speak, and no hidden state.

## 5. Bots in scope at launch

| Bot | Mode | Cadence | Notes |
|---|---|---|---|
| SPY Daily Mean Reversion (`spy_mr_bot`) | paper → live | 2 runs/day (15:50 decide, 09:45 reconcile) | Exists. Must be adapted to the SDK (see Architecture §4) without changing its trading rules. |
| Future bots | — | any | Must be able to join by importing the SDK and declaring a manifest. |

## 6. Functional requirements

### 6.1 Fleet overview (home)
- F1. Portfolio tiles: broker liquidation value, day P&L vs daily loss limit, gross exposure vs cap, portfolio drawdown vs ladder, fleet health counts (running / degraded / paused / killed).
- F2. Bot table, default sort by risk (degraded first, then in-position, then live before paper). Columns: name + strategy line, mode badge, position, day P&L, drawdown, parity verdict, last heartbeat, open →.
- F3. "Needs attention" feed: parity drift, missed heartbeat, token expiry, calendar events, limit breaches. Each item has a severity, a source and a timestamp.
- F4. Strategy correlation matrix (60-day daily returns of each bot's equity). Pairs above 0.7 are flagged with a sentence.
- F5. Today's schedule with done/pending marks, open orders reconciled to broker, recent fills with slippage vs the bot's backtest assumption.
- F6. KILL ALL button always visible in the header.

### 6.2 Bot detail
- F7. Header: status dot, name, mode, version, one-line rule summary, actions: Re-check signal, Pause after exit, Flatten now…, Kill bot….
- F8. Tiles: position (or FLAT + last trade), signal now (all indicator values + distance to trigger), allocated equity and caps, health (heartbeat, feed freshness, broker-vs-state match, next run).
- F9. Live-vs-backtest chart: equity curve over backtest median and 5–95% band. Parity table: trades, win rate, avg win/loss, slippage per fill, verdict.
- F10. Per-bot risk limits with usage bars. Parameters panel, versioned; editing creates a new version and resets the parity band start.
- F11. Trades table with entry/exit, qty, prices, bars, reason, P&L, slippage; CSV export.
- F12. Decision log: every run, every reason, newest first.

### 6.3 Risk & controls
- F13. Kill switch panel: KILL ALL (two-step: click, then type the shown word), Flatten all keep bots, Pause new entries. Shows armed state and last drill date.
- F14. Portfolio drawdown ladder, measured on **broker liquidation value**: −6% pause new entries; −8% flatten the most correlated pair; −10% kill, manual re-arm. Thresholds editable with audit.
- F15. Pre-trade checks table: max order size, max gross exposure, price collar vs last quote, orders per bot per day, stale-data guard, duplicate-order guard, position-vs-state reconciliation. Shows limit, today's peak, action on breach.
- F16. Heartbeats and dependencies: scheduler, Schwab API latency, token days left, market calendar loaded, host PC awake/disk, alert channel test.
- F17. Control audit log: who, when, what changed, before → after.

### 6.4 Alerts
- F18. Two channels: **page** (SMS or push) and **digest** (morning email/summary). Page only for: kill fired, limit breach rejected an order, missed heartbeat > 10 min on a live bot, broker position ≠ state, token < 2 days. Everything else goes to the digest.
- F19. Alert test button; last test time shown on Risk page.

### 6.5 Journal and Research (v1: stubs)
- F20. Journal: per-trade notes, tag, screenshot attach. v1 ships the data model and a list view only.
- F21. Research: promotion workflow paper → live with gates (≥ N paper trades, parity within band, slippage ≤ assumption, operator sign-off). v1 ships the gate checklist on the bot page; no backtest runner.

## 7. Non-functional requirements

- N1. Local only by default: binds 127.0.0.1. Phone access via Tailscale, documented, off by default.
- N2. Risk checks are **library calls inside the bot process**, not HTTP calls, so a dead Command Center cannot disable risk checks. A dead Command Center must also never block a risk-reducing order.
- N3. Kill state lives in a file *and* the database; bots read the file. A bot that cannot read the kill file treats it as KILLED.
- N4. Every control action is written to the audit log before it takes effect.
- N5. Page load < 1 s on the trading PC; data refresh every 15 s via polling (no websockets in v1).
- N6. All times displayed in America/New_York. Stored in UTC.
- N7. Tests: unit tests for risk engine and SDK; integration test that drives a fake bot through entry, stop, exit and kill.
- N8. No secrets in the repo. `.env` and token files are git-ignored. The Command Center never reads bot `.env` files.

## 8. Success criteria

- The existing `spy_mr_bot` runs unchanged in behavior after SDK adoption (same signals, same orders, verified by replaying its log).
- Kill drill: from clicking KILL ALL to all bots disabled and all paper positions flattened in < 5 s, with an audit entry.
- A deliberately silenced bot shows as degraded within 10 minutes and pages the operator.
- An order exceeding max size is rejected by the SDK with no network call to the broker, and the rejection appears in the UI.

## 9. Design reference

The approved visual design is the Claude Design canvas "Trading Bot Fleet Dashboard" (three artboards: Fleet overview, Bot detail, Risk & controls). `03_DESIGN_SPEC.md` transcribes it. Match it; do not redesign.
