# Architecture

## 1. Shape

```
┌──────────────────────────────── trading PC (Windows) ────────────────────────────────┐
│                                                                                       │
│  bots/spy_mr_bot/bot.py ──┐                                                           │
│  bots/<next_bot>/bot.py ──┼─ import cc_sdk ──► risk checks (in-process) ──► Schwab   │
│  ...                      │        │                                                  │
│                           │        └─ writes: heartbeats, decisions, orders, fills,   │
│                           │                   positions, equity  ──► SQLite (cc.db)  │
│                           │                                                           │
│  Windows Task Scheduler ──┘ (unchanged: one task per bot command)                     │
│                                                                                       │
│  cc_server (FastAPI, 127.0.0.1:8585)                                                  │
│    ├─ reads cc.db, serves JSON API                                                    │
│    ├─ riskd: evaluates portfolio ladder, heartbeats, parity; writes alerts            │
│    ├─ control actions: pause / flatten / kill / re-arm  → writes control files + db   │
│    └─ serves the built React app (static)                                             │
│                                                                                       │
│  cc_web (React + Vite + TypeScript)  ← the three designed screens                     │
└───────────────────────────────────────────────────────────────────────────────────────┘
```

Design principle: **bots must stay safe when the server is down.** Risk limits, kill state and the
order ledger are enforced and written by the SDK inside the bot process. The server reads, aggregates,
alerts and issues control files. It never sits in the order path.

## 2. Repository layout

```
command-center/
  CLAUDE.md
  README.md
  pyproject.toml                # workspace: cc_sdk, cc_server
  cc_sdk/                       # pip-installable, imported by every bot
    cc_sdk/__init__.py
    cc_sdk/manifest.py          # BotManifest dataclass + validation
    cc_sdk/ledger.py            # SQLite writes: heartbeat, decision, order, fill, position, equity
    cc_sdk/risk.py              # pre_trade_check(), limits loader, kill-file reader
    cc_sdk/control.py           # read pause/kill flags; "risk-reducing" classification
    cc_sdk/schema.sql
    tests/
  cc_server/
    cc_server/main.py           # FastAPI app, static mount
    cc_server/api/              # routers: fleet, bots, risk, alerts, controls
    cc_server/riskd.py          # background loop every 15 s
    cc_server/parity.py         # live-vs-backtest band maths
    cc_server/alerts.py         # page vs digest routing; Twilio/SMTP adapters behind an interface
    cc_server/calendar.py       # NYSE holidays + early closes
    tests/
  cc_web/
    package.json, vite.config.ts, tsconfig.json
    src/
      app/                      # routes: /, /bots/:id, /risk, /journal, /research
      components/               # Tile, BotTable, AttentionFeed, CorrelationMatrix, EquityBand, LimitBar, KillSwitch, AuditLog, ...
      lib/api.ts                # typed client generated from OpenAPI
      lib/format.ts             # money, pct, ET time
      styles/tokens.css         # design tokens from 03_DESIGN_SPEC
  bots/
    spy_mr_bot/                 # existing bot, adapted to cc_sdk (rules untouched)
    _template_bot/              # minimal bot showing SDK usage
  var/                          # runtime, git-ignored: cc.db, control/, logs/
  scripts/
    install_tasks.ps1           # scheduler tasks for server + bots
    kill_drill.py               # exercises the kill path end to end against paper bots
```

## 3. Data model (SQLite, `var/cc.db`, WAL mode)

All timestamps UTC ISO-8601. All money in USD as REAL. `bot_id` is the manifest `id`.

```sql
bots(id TEXT PK, name, strategy_line, mode TEXT CHECK(mode IN('paper','live')), version TEXT,
     instrument, cadence_json, backtest_json, limits_json, status TEXT, created_at, updated_at)
heartbeats(id INTEGER PK, bot_id, run TEXT, at, ok INTEGER, detail TEXT)
decisions(id INTEGER PK, bot_id, at, run TEXT, signal_json, action TEXT, reason TEXT)
orders(id INTEGER PK, bot_id, at, broker_order_id, side, qty, type, limit_price, stop_price,
       status, reason, risk_result_json)
fills(id INTEGER PK, order_id FK, at, qty, price, expected_price, slippage, commission)
positions(bot_id PK, symbol, qty, avg_price, entry_at, bars_held, updated_at)
equity(id INTEGER PK, bot_id, at, equity, source TEXT CHECK(source IN('bot','broker')))
trades(id INTEGER PK, bot_id, entry_at, exit_at, qty, entry_px, exit_px, bars, exit_reason, pnl, slippage)
alerts(id INTEGER PK, at, severity TEXT CHECK(severity IN('page','digest','info')), bot_id, kind, message,
       acknowledged_at)
controls(id INTEGER PK, at, actor, action, target, before_json, after_json, note)
limits(scope TEXT, key TEXT, value_json, updated_at, PRIMARY KEY(scope,key))   -- scope: 'portfolio' or bot_id
journal(id INTEGER PK, trade_id, at, tags, note, attachment_path)
```

Control flags live in **files** so bots can read them with no DB dependency:

```
var/control/KILL            # exists => killed. Content: {"at", "actor", "reason"}
var/control/PAUSE_ENTRIES   # exists => no new entries fleet-wide
var/control/<bot_id>.pause  # exists => that bot takes no new entries
var/control/<bot_id>.kill   # exists => that bot is disabled
```

## 4. SDK contract (`cc_sdk`)

Every bot declares a manifest and wraps its order calls. Nothing else changes.

```python
from cc_sdk import Bot, BotManifest, Order

MANIFEST = BotManifest(
    id="spy_mr", name="SPY Daily Mean Reversion", version="1.2",
    strategy_line="RSI(2) < 10 above SMA200 · exit SMA5 / 10 bars · 5% stop",
    instrument="SPY", mode="paper",
    cadence={"decide": "15:50", "reconcile": "09:45"},
    backtest={"win_rate": 0.77, "profit_factor": 2.28, "avg_win": 0.0121, "avg_loss": -0.0081,
              "trades_per_year": 5, "slippage_assumed": 0.01, "max_dd": 0.116,
              "equity_median_path": "backtests/spy_mr_median.csv"},
    limits={"max_position_usd": 100000, "max_orders_per_day": 2, "max_bot_dd": 0.12,
            "max_consecutive_losses": 4, "price_collar_pct": 0.015, "stale_quote_s": 90},
)

bot = Bot(MANIFEST)                      # registers/updates row in bots table

with bot.run("decide") as run:           # writes heartbeat at exit, ok/failed, with exception text
    run.decision(signal={...}, action="BUY_MOC", reason="rsi2_entry")
    result = bot.risk.pre_trade(Order(side="BUY", qty=153, type="MOC", ref_price=651.20,
                                      quote_age_s=0.4, reduces_risk=False))
    if result.ok:
        oid = schwab.buy_moc("SPY", 153)
        run.order_sent(result, broker_order_id=oid)
    else:
        run.order_rejected(result)       # also raises an alert row

bot.record_fill(order_id, qty, price, expected_price, commission)
bot.set_position(symbol, qty, avg_price, entry_at, bars_held)
bot.record_equity(value, source="broker")
```

`pre_trade()` evaluates, in order, and **fails closed**:
1. kill file (fleet or bot) → reject unless `reduces_risk`
2. pause file (fleet or bot) → reject new entries, allow `reduces_risk`
3. max order size, max position, max gross exposure (uses latest `equity(source='broker')` across bots)
4. price collar vs `ref_price` and `stale_quote_s`
5. orders-per-day count, duplicate (same bot, side, calendar day)
6. consecutive-loss and bot-drawdown auto-pause (writes `<bot_id>.pause` and an alert)

Rejections are written to `orders` with `status='rejected'` and to `alerts` with `severity='page'` for live bots.

## 5. Server (`cc_server`)

- FastAPI, uvicorn, bound to `127.0.0.1:8585`. Serves `/api/*` and the built `cc_web/dist`.
- `riskd` loop (asyncio, every 15 s): computes portfolio DD from latest broker equity → applies ladder (writes control files + controls row + alert); checks heartbeats against cadence (miss > 10 min on a live bot → page); recomputes parity verdicts; refreshes Schwab token-days-left from the token file's mtime (**read-only**; the server never holds credentials).
- Control endpoints (`POST /api/controls/{kill_all|flatten_all|pause_entries|rearm|bot/{id}/{pause|flatten|kill|rerun}}`) require a confirmation token for kill/flatten (server issues a random word; client must echo it). Each writes `controls` first, then acts.
- Flatten: the server does not place orders. It writes `var/control/<bot_id>.flatten` and triggers the bot's `reconcile` command via `subprocess`; the bot's SDK sees the flag and closes its position through its own broker client. This keeps credentials in the bot.
- Alerts: `alerts.py` routes `page` to the configured channel (Twilio SMS adapter first; email adapter second), `digest` into a 06:00 ET summary. Channel config in `var/alerts.toml`.

## 6. Web (`cc_web`)

- React 18 + Vite + TypeScript. Routing: react-router. Data: TanStack Query, 15 s polling.
- Charts: `uplot` for the equity band (fast, tiny); CSS bars for limits; CSS grid for the correlation matrix. No chart library with a theme engine.
- Styling: plain CSS modules with tokens from `03_DESIGN_SPEC.md`. No Tailwind, no component kit; the design is specific and small.
- Accessibility: real `<button>` and `<a>`, labels on icon buttons, 4.5:1 contrast, keyboard reachable kill switch.

## 7. Adapting `spy_mr_bot`

1. Add `MANIFEST` and `Bot(MANIFEST)`; wrap `cmd_decide` and `cmd_reconcile` bodies in `bot.run(...)`.
2. Replace `log.info(...)` decision lines with `run.decision(...)` (keep the log line too).
3. Wrap `b.buy_moc / b.sell_moc / b.place_stop` with `bot.risk.pre_trade` (stops are `reduces_risk=True`).
4. After reconcile, call `record_fill`, `set_position`, `record_equity`.
5. Honor flatten flag: in `reconcile`, if `bot.control.flatten_requested()` and in position → `sell_moc` (or market if before 15:45 ET), then clear the flag.
6. Rules in `strategy.py` are **not** touched. Add a test that replays `tests/fixtures/spy_log_sample.jsonl` through old and new code paths and asserts identical decisions.

## 8. Security

- Localhost bind. Optional Tailscale documented in README; no public exposure.
- No credentials in the server. Bot `.env` files are never read by the server.
- Control endpoints: same-origin only, confirmation word for destructive actions, full audit.
- SQLite file permissions: user-only.

## 9. Observability

- Server logs JSON lines to `var/logs/server.log`; bots keep their own logs.
- `/api/health` returns scheduler status, db size, riskd last tick, alert channel last test.
