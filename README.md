# Trading Bot Command Center

One local web app that supervises every trading bot on this PC: position, signal, live-vs-backtest parity,
heartbeats, risk limits, drawdown ladder, kill switch, audit log. Schwab is the only broker. Risk checks run
**inside each bot's process** (`cc_sdk`) and fail closed, so a dead dashboard can never disable them.

```
bots/*/bot.py  --import cc_sdk-->  risk check -> Schwab        (order path; server is NOT in it)
       |                                 \-> var/cc.db (SQLite ledger)
cc_server (127.0.0.1:8585)  reads cc.db, runs riskd, serves cc_web, writes control files in var/control/
```

## Install (Windows, Python 3.11+, Node 20+)

```powershell
git clone <this repo> command-center ; cd command-center
python -m venv .venv ; .\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
cd cc_web ; npm ci ; npm run build ; cd ..
python scripts\seed_demo.py --reset          # optional: demo data to see the screens
python -m cc_server.main                     # http://127.0.0.1:8585
```

Run the tests any time: `python -m pytest -q` (Python) and `cd cc_web && npm test` (web).
Linux/macOS dev: `make dev`, `make test`, `make seed`, `make drill`.

## Daily operation

Install the scheduled tasks once (server at logon; daily bots `decide` 15:50 and `reconcile` 09:45; intraday bots one
`session` task at 09:25; nightly backup):

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_tasks.ps1
```

Then open http://127.0.0.1:8585. The Fleet page answers three questions in five seconds: is anything broken
(degraded rows, missed heartbeats), is anything bleeding (day P&L, drawdown), can I stop it (KILL ALL, always
top right).

### Weekly: Schwab re-auth
Schwab refresh tokens expire after 7 days. The header chip shows days left (from the token file's modification
time; the server never reads the token). Under 2 days triggers a page alert. In each bot folder:
`python bot.py auth`.

### Early-close days
On 1:00 pm closes (day after Thanksgiving, Christmas Eve, 7/3) the server posts a reminder the day before.
Run `python bot.py decide` manually at 12:50 pm in each daily bot's folder, or edit the Task Scheduler time.

### Monthly: kill drill
`python scripts\kill_drill.py` exercises the real kill path against paper bots and records a `drill` audit row.
It refuses to run if any live bot is registered unless you pass `--include-live` deliberately.

## Intraday bots and research

`research/` is the strategy harness: 12 intraday rule sets (`research/strategies.py`), a backtester with costs, walk-forward
folds and a pre-registered pass bar (`research/engine.py`), run with `python -m research.run_all`. Data goes in
`var/data/<SYMBOL>_1m_rth.parquet` (1-minute RTH bars; the shipped results used 2005–2020 index CFD bars as SPY/QQQ/IWM
proxies). Results and verdicts: `docs/RESEARCH_RESULTS.md`. Nothing in `research/` is on the order path.

Intraday bots share `cc_sdk.intraday.SessionRunner`: one process per bot per session (09:25 → close), 15-second polling,
Schwab minute bars and quotes, **paper fills at quote ± 1 bp**, stops checked on every poll, flat by 15:58, control flags
honored on every poll, heartbeat every 5 minutes (the server flags a dead session within the grace window). One trade per
symbol per day. Bots: `bots/gap_go_bot` (passed research), `bots/nr7_bot` (watch list, below bar), `bots/sip_orb` (stocks in
play from the M2M scanner via `SCANNER_URL`; contract in `sip_scanner.py`).

Offline dry run without Schwab: `python bot.py replay 2020-05-08 SPY` in a bot folder replays a research day through the
real runner; the trades, decisions and fills appear on the dashboard. Entry parity with the research rules is tested
(`cc_sdk/tests/test_intraday.py`); stop exits in the runner fill at the next quote after the stop is crossed, so they are
equal or worse than the backtest's stop-price fills by construction.

Real ETF minute data from Schwab (once a bot folder has working credentials): from that folder run
`python ..\..\research\schwab_dump.py SPY QQQ IWM`, then `python -m research.run_all --symbols SPY,QQQ,IWM` from the repo
root. The dump appends to `var/data/<SYM>_1m_rth.parquet`, so a weekly run accumulates history beyond Schwab's lookback.

Promotion rule (paper → live) is the research bar applied to paper results: PF ≥ 1.3 after costs on ≥ 200 trades, positive
in every quarter, with live-vs-backtest parity "within band". No bot has met it yet.

## Adding a bot

1. Copy `bots/_template_bot/` to `bots/<name>/`.
2. Fill in `MANIFEST` (id, name, cadence, backtest stats, limits). The backtest stats drive the parity band.
3. Wrap each scheduled command in `with bot.run("decide") as run:`; route every order through
   `bot.risk.pre_trade(Order(...))` and call `run.order_sent(...)` on success; call `bot.record_fill`,
   `bot.set_position`, `bot.record_equity` after reconciling with the broker.
4. Honor `bot.control.flatten_requested()` in your reconcile: close the position through your own broker
   client and `bot.control.clear_flatten()`.
5. Re-run `install_tasks.ps1`. The bot appears on the Fleet page after its first run.

`bots/spy_mr_bot/cc.py` shows a real adaptation where the strategy file is frozen and all SDK calls live in a shim.

## Controls and what the files mean

All controls are files in `var/control/`, written by the server (after an audit row) or by the SDK (auto-pause):

| File | Meaning | Who clears it |
|---|---|---|
| `KILL` | Fleet killed. No new entries anywhere. Bots flatten on next run. | Re-arm (header or Risk page), typed-word confirm |
| `PAUSE_ENTRIES` | No new entries fleet-wide; exits and stops still allowed | Risk page "Resume new entries", or re-arm |
| `<bot>.pause` | That bot takes no new entries | Bot page "Resume entries" |
| `<bot>.kill` | That bot disabled | Bot page "Resume entries" |
| `<bot>.flatten` | Close position on next run | The bot itself after flattening |

A missing `var/control/` directory is treated by every bot as KILLED.

## Risk limits

Portfolio limits (Risk page, each edit audited with a note): daily loss −2.0%, gross exposure 1.50×, drawdown
ladder −6% pause / −8% flatten most-correlated pair / −10% kill, heartbeat grace 10 min.
Per-bot limits come from the manifest: max order $150k / 2,000 sh, max position, 2 orders/day, 12% bot drawdown,
4 consecutive losses, ±1.5% price collar, 90 s stale-quote guard. Drawdown is measured on **broker** equity.

## Alerts

`var/alerts.toml` (created on first run) selects channels. `page` = immediate (SMS via Twilio or email); `digest`
= 06:00 ET summary. Secrets come from environment variables named in the file, never from the file. Test from
the Risk page.

What pages: kill fired, ladder step, order rejected on a live bot, missed heartbeat on a live bot, broker ≠ state,
token < 2 days, parity drift on a live bot. Everything else goes to the digest.

## Phone access (optional, off by default)

The server binds 127.0.0.1 only. For your phone, install Tailscale on the PC and phone and open
`http://<pc-tailscale-name>:8585` after changing the bind in `cc_server/main.py` to the Tailscale IP.
Do not expose this to the public internet; there is no login.

## Recovery

- Server down: bots keep running and keep enforcing limits; the UI is unavailable; `riskd` ladder and alerts pause.
  Restart with the "CC server" task.
- Bot crashed mid-run: its heartbeat shows ✗ with the traceback in `heartbeats.detail`; the Fleet row goes
  degraded; re-run the command by hand (`python bot.py reconcile`) after reading the log.
- Database corrupt: restore the newest `var/backups/cc-YYYYMMDD.db` over `var/cc.db` with the server stopped.
- Stale control file after a crash: read the JSON inside it (who/when/why) before deleting it.

## Layout

See `docs/02_ARCHITECTURE.md`. Specs in `docs/`. Decisions taken during the build in `docs/DECISIONS.md`.
