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

## M6 — intraday research and runner (2026-10-03)

- **Research before bots.** Twelve intraday families were coded as pure rules and backtested on 15 years of minute data
  with a pass bar fixed before the run. Only gap-and-go passed (SPX, NAS). ORB variants, VWAP reversion/trend, first-hour
  break, volatility breakout, gap fade, overnight momentum and afternoon fade failed on every symbol. Details and the
  2008-concentration caveat in `docs/RESEARCH_RESULTS.md`.
- **Index CFD bars as ETF proxies.** The sandbox could reach no market-data vendor; Oanda SPX500/NAS100/US2000 1-minute
  bars (2005–2020) were the only minute history available. Price behaviour tracks the ETFs; volume is tick count. Survivors
  are rechecked on Schwab minute data on the trading PC before paper trading is trusted.
- **Positions are per (bot, symbol).** `positions` PK changed from `bot_id` to `(bot_id, symbol)`, with `stop_price` and
  `side`; a flat symbol has no row. The ledger migrates the old table once. The duplicate-order guard is per symbol.
- **One runner, many rule sets.** `cc_sdk.intraday.SessionRunner` owns the loop, risk, paper fills, stops, EOD flatten and
  controls; a bot supplies pure `Rules` and (optionally) a late-binding universe function (sip_orb at 09:35).
- **Replay through the real runner** rather than a separate simulator, so the dashboard path is exercised offline and
  entry parity with the research code is a test, not a claim.
- **Watch-list bots are allowed on paper** (nr7) and labelled as below the bar in their manifest `backtest.source`, so the
  parity band and the UI never imply an edge that was not shown.
- **One Schwab token for the fleet.** Schwab issues one refresh token per app per user; per-bot token files would
  invalidate each other on every `auth`. All bots and the research dump now read `var/schwab_token.json`; `TOKEN_PATH`
  in a bot's `.env` opts out for a bot on a different app. `from_env` refuses keys/secrets that are not 32/16 chars.
- **Adopt M2M's existing Schwab login rather than minting a second token.** Schwab issues the refresh token at login and
  does not rotate it when access tokens are minted, so one refresh token can serve both M2M and the Command Center for its
  7-day life. `python bot.py auth --from-token` writes schwab-py's token file with an expired access token; the first call
  refreshes it. Token age is tracked in a sidecar `.issued` file because schwab-py rewrites the token file every 30 min
  (file mtime was a wrong signal for days-left).
- **All Command Center bots are paper.** No intraday code path places an order; Schwab is data only. The daily bot's live
  path stays behind MODE=live plus an explicit LIVE_CONFIRM.
