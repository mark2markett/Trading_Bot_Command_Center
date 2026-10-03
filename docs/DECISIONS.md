# Decisions taken during the build

| Date | What | Why |
|---|---|---|
| 2026-10-03 | `spy_mr_bot` adaptation goes through a `cc.py` shim; `bot.py` gets small edits, `strategy.py` untouched (sha pinned by test) | Hard rule 4. The shim also lets the bot run without cc_sdk present, fail-closed for new entries. |
| 2026-10-03 | ruff: line length and import-order rules relaxed for `bots/spy_mr_bot/**` | The bot predates the repo; reformatting it would create a noisy diff on a frozen file. |
| 2026-10-03 | Bot equity queries filter `source='bot'`; account-level rows are `source='broker'` | Found while rendering: mixing them broke the correlation matrix and the bot-drawdown auto-pause. |
| 2026-10-03 | Backtest band is scaled to the live series' x-axis (trades per point) | Live equity is daily; backtest stats are per trade. Without scaling the band ended at trade 12 on a 90-day chart. |
| 2026-10-03 | Confirm-word store is in-memory, single use | Localhost, single operator. Persisting it would add a table for no safety gain. |
| 2026-10-03 | Flatten is executed by the bot, not the server | Keeps broker credentials inside the bot (hard rule 5). Server writes `<bot>.flatten` and triggers the bot's reconcile. |
| 2026-10-03 | `var/alerts.toml` created on first run with console channels | Nothing pages until the operator configures it; the Risk page test button shows which channel is active. |
| 2026-10-03 | Journal = alert history; Research = promotion gate checklist | PRD v1 stubs. Real trade notes and a backtest runner are in BACKLOG. |
