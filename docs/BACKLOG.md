# Backlog (not in v1)

- Journal: per-trade notes, tags, screenshot attach (schema exists: `journal` table).
- Research: walk-forward parameter grid runner, paper→live promotion workflow with sign-off recorded in `controls`.
- Options bot card: delta, theta, DTE, margin usage (current fields are equities-shaped).
- Broker-vs-state mismatch count on the Risk page (SDK reconciles; counter not yet surfaced).
- Early-close automatic reschedule of the Task Scheduler `decide` time (today: reminder + manual run).
- Live equity vs backtest band keyed to trade count instead of days as an option.
- Websocket push instead of 15 s polling.
- Tailscale bind option in config instead of code edit.

## After M6

- Recheck gap_go / nr7 on Schwab minute data (SPY, QQQ, IWM) from the PC once `python bot.py auth` works
  (`research/schwab_dump.py` is in place; needs credentials).
- Options paper strategies (0DTE condor after the range sets, directional debit spread off gap_go, straddle into range
  expansion, 7–14 DTE vertical on the daily MR signal): need an options paper-fill engine over Schwab chains (mid ± slippage)
  and an options position model; forward paper only, no historical chains available.
- Small-cap universe backtest requires per-stock minute data with real volume; not possible on the current data.
- Runner stop handling: optional protective stop order at the broker in live mode (today paper-only, quote-checked).
- `power_hour` SPX: investigate non-2008 drivers before reconsidering.
