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
# Demo seeding requires an external sandbox; see Safe demo data below.
python -m cc_server.main                     # http://127.0.0.1:8585
```

Run the tests any time: `python -m pytest -q` (Python) and `cd cc_web && npm test` (web).
Linux/macOS dev: `make dev`, `make test`, `make seed`, `make drill`.

## Closed-loop sandbox test

Run from the repository root, on the `test/closed-loop` branch:

```powershell
.venv\Scripts\python.exe scripts\closed_loop.py
```

Linux/macOS: `.venv/bin/python scripts/closed_loop.py`.
Install development dependencies with `pip install -e ".[dev]"`; install
`pyarrow` for parquet replay and `tzdata` on Windows if needed. In `cc_web`,
run `npm ci`, `npm test`, and `npm run build`. Browser checks use Playwright;
run `npx playwright install chromium` in `cc_web`, or set
`CC_PLAYWRIGHT_EXECUTABLE` to an existing Chromium executable. On Linux the
harness detects `chromium` on PATH. Dependency/TLS verification stays enabled.

The launcher creates `%TEMP%\cc-closed-loop-<unique-id>\var` (the system temp
directory on other platforms), then gives every worker an explicit `CC_VAR`
and paper mode. It refuses inherited live mode and unsafe CC_VAR paths. It
never uses the running server on 8585, reuses a listener on 8586, runs scheduled
bot commands, sends live orders, or copies alert/credential files. It refuses
a sandbox with a sibling `bots` folder that server controls could spawn.
Internal worker/server entrypoints also require launcher-created ownership
metadata and a matching run token; they cannot adopt or delete caller folders.
Database/control aliases are refused. Python write/SQLite audit hooks run
before bot/server imports, block supported writes outside the owned run, and
retain operation-only evidence. Bytecode writes are disabled. This observes
supported Python operations; it is not an OS-wide trace of native libraries.

The loop exercises the actual five bot manifests and rules, risk checks,
paper fills, SQLite ledger, built dashboard, confirmation controls, and bot
responses. Scripted prices/chains/calendars are labeled **SYNTHETIC**. API and
UI behavior have separate assertions: an API flatten can work while its
operator button is broken, and the report preserves that distinction.

Each check reports **PASS**, **FAIL**, or **NOT COVERED**. Exit 0 means no
failures; it does not mean complete coverage. Exit 1 means a failed assertion
or execution/cleanup failure; exit 2 means a safety refusal. The report's
function inventory records observed calls and unexercised functions, not a
claim that every branch of a called function was tested.

Reports (`report.md` and `report.json`) and fleet/spread screenshots remain
in the temporary run folder printed by the command. Sandbox databases,
controls, logs, and isolated daily-bot source/state are removed after owned
processes and SQLite handles close. If cleanup fails, the command exits
nonzero and reports the retained sandbox. An interrupted/crashed worker also
gets a failure report; its server is stopped only after matching its recorded
run identity.

On the trading PC, local `var/data/*_1m_rth.parquet` enables a bounded replay
search of at most 250 trading days. Source data is read only; needed bars are
prepared under the sandbox. The live `var/cc.db` is fingerprinted through a
read-only connection before/after: table counts, maximum IDs where available,
logical row hashes, and control-file metadata/hashes. Heartbeats and kv are
excluded. A changed fingerprint fails, even if concurrent live activity is a
possible cause. A source-only clone/bundle has neither history nor live state,
so those checks are **NOT COVERED** rather than claims about the Windows host.

Real-feed checks use only already injected variables; they do not load `.env`
or token files. Missing authentication is **NOT COVERED**. Shared-state Schwab
authentication can rotate a token and write Supabase, so it is excluded from
this isolated test. The token-broker GET can also refresh remote authentication,
so Schwab checks remain **NOT COVERED** even when broker variables are injected;
the harness never contacts it. Polygon can use an injected `POLYGON_API_KEY`.
Never enter credentials in a report or Git. A failed actual
data request is a failure, not silently converted to missing coverage.

### Safe demo data

`seed_demo.py` now refuses unset or checkout-contained CC_VAR before opening
or resetting a database, including database/control symlinks and junctions.
To seed a disposable demo:

```powershell
$previousVar = $env:CC_VAR
$env:CC_VAR = Join-Path $env:TEMP 'cc-demo\var'
python scripts\seed_demo.py --reset
$env:CC_VAR = $previousVar
```

An explicit `--live-ledger` override permits intentional repository-ledger
seeding. It can replace the paper record when combined with `--reset`; it is
not needed for the closed-loop harness. `kill_drill.py` retains its operational
behavior against the running server/live ledger and is not this sandbox test.

## Daily operation

Install the scheduled tasks once (server at logon; daily bots `decide` 15:50 and `reconcile` 09:45; intraday bots one
`session` task at 09:25; nightly backup):

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_tasks.ps1
```

Then open http://127.0.0.1:8585. The Fleet page answers three questions in five seconds: is anything broken
(degraded rows, missed heartbeats), is anything bleeding (day P&L, drawdown), can I stop it (KILL ALL, always
top right).

### Weekly: Schwab re-auth (done in M2M, not here)
Schwab refresh tokens expire after 7 days. **This fleet never logs into Schwab and never holds a refresh token or the
app's Client Secret.** M2M (`mark2markets.com`) owns the one Schwab login and its weekly re-authorization at
`/trades/schwab-reauth`; the fleet asks M2M's broker (`GET /api/internal/schwab/access-token`) for a 30-minute access
token whenever it needs one. Each bot's `.env.local` holds only `CC_TOKEN_BROKER_URL` and `CC_TOKEN_BROKER_SECRET`
(gitignored). Revoking the fleet is one env-var change in Vercel; it never touches Schwab.

The header chip shows days left for M2M's refresh token, taken from the non-secret sidecar `var\schwab_token.json.issued`
that the SDK writes from the broker's `refresh_issued_at`. Under 2 days triggers a page alert — that is M2M's re-auth
coming due. `python bot.py check` in any bot folder proves the brokered token works with one quote and today's
minute-bar count. `python bot.py auth` no longer exists (exit 2 with an explanation).

Why not share the refresh token (the M6.7 design): Schwab rotates the refresh token on refresh, so two systems
refreshing the same token race each other and one goes dead (`invalid_grant`, 2026-10-03). Design record:
m2m-platform `docs/SCHWAB-ACCESS-TOKEN-BROKER-SPEC-2026-10-03.md`.

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
