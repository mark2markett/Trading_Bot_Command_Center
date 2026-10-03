# Backlog (not in v1)

- Journal: per-trade notes, tags, screenshot attach (schema exists: `journal` table).
- Research: walk-forward parameter grid runner, paper→live promotion workflow with sign-off recorded in `controls`.
- Options bot card: delta, theta, DTE, margin usage (current fields are equities-shaped).
- Broker-vs-state mismatch count on the Risk page (SDK reconciles; counter not yet surfaced).
- Early-close automatic reschedule of the Task Scheduler `decide` time (today: reminder + manual run).
- Live equity vs backtest band keyed to trade count instead of days as an option.
- Websocket push instead of 15 s polling.
- Tailscale bind option in config instead of code edit.
