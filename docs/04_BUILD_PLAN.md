# Build Plan

Six milestones. Each has a definition of done and a verification step that Claude Code must run and report
before moving on. Do not start a milestone until the previous one's checks pass. Commit at the end of each.

## M0 — Repo and tooling (½ day)

Done when:
- Monorepo laid out as in `02_ARCHITECTURE.md §2`. `pyproject.toml` with `cc_sdk` and `cc_server` as packages; `cc_web` with Vite + React + TS.
- `make dev` (or `scripts/dev.ps1`) starts server + web in dev mode; `make test` runs Python and web tests.
- `.gitignore` covers `var/`, `.env*`, `*token*.json`, `node_modules`, `dist`.
- CI-free; everything runs locally on Windows and Linux.

Verify: `make test` passes with placeholder tests; `make dev` serves "Command Center" at http://127.0.0.1:8585.

## M1 — SDK and ledger (1–2 days)

Done when:
- `cc_sdk` implements `BotManifest`, `Bot`, `Bot.run()` context manager, `risk.pre_trade()`, control-file readers, ledger writes, schema migration on first use.
- `pre_trade()` enforces all six checks in `02_ARCHITECTURE.md §4`, fails closed, allows `reduces_risk` orders under pause/kill.
- `bots/_template_bot` demonstrates every SDK call in < 80 lines.

Verify (unit tests, all must pass):
- kill file present → entry rejected, stop allowed.
- order over max size → rejected, `orders.status='rejected'`, alert row with `severity='page'` when mode is live, `'digest'` when paper.
- duplicate same-day same-side → rejected.
- stale quote → rejected.
- 4th consecutive loss → `<bot_id>.pause` written and alert raised.
- missing `var/control/` directory → treated as killed (fail closed).
- heartbeat written on normal exit and on exception (with traceback text).

## M2 — Adapt `spy_mr_bot` (1 day)

Done when:
- Bot imports `cc_sdk`, declares `MANIFEST`, wraps both commands in `bot.run()`, routes all orders through `pre_trade()`, records fills/positions/equity, honors flatten flag.
- `strategy.py` unchanged (diff must be empty).
- Existing 5 tests still pass; new replay test proves identical decisions before/after.

Verify: run `python bot.py check`, `reconcile`, `decide` in paper mode; rows appear in `heartbeats`, `decisions`; `git diff --stat bots/spy_mr_bot/strategy.py` is empty.

## M3 — Server and riskd (2 days)

Done when:
- FastAPI app with routers: `GET /api/fleet`, `GET /api/bots`, `GET /api/bots/{id}`, `GET /api/bots/{id}/trades|decisions|equity`, `GET /api/risk`, `GET /api/alerts`, `GET /api/health`, `POST /api/controls/...` (with confirmation-word flow), `PUT /api/limits/{scope}/{key}`.
- `riskd` loop: portfolio DD ladder, heartbeat watchdog, parity recompute, token-days-left (from token file mtime, read-only), correlation matrix (60-day daily bot equity returns).
- `parity.py`: band from manifest backtest stats (binomial CI for win rate; bootstrap of backtest trade distribution for equity path if `equity_median_path` present, else analytic normal approx). Verdict: `within`, `drift` (outside 2σ on any of win rate / avg loss / slippage), `failed` (operator-set).
- `alerts.py`: routing rules from PRD F18; adapters: console (default), Twilio SMS, SMTP. Config in `var/alerts.toml`. Test endpoint.
- `calendar.py`: NYSE holidays and early closes through 2027; exposes next early close; riskd posts a digest alert the day before.
- OpenAPI schema exported to `cc_web/src/lib/api.schema.json`.

Verify (integration test `cc_server/tests/test_kill_path.py`):
- Start server against a temp `var/`. Run the template bot to open a paper position. `POST /api/controls/kill_all` with wrong word → 400; with right word → `var/control/KILL` exists, `controls` row written **before** the file, bot's next `reconcile` flattens, `/api/fleet` shows KILLED, alert `page` raised. Whole path < 5 s.
- Silence test: insert a bot with cadence 09:45 and no heartbeat; advance clock mock 11 min; riskd marks degraded and raises `page`.

## M4 — Web app (3 days)

Done when:
- Three routes match `03_DESIGN_SPEC.md` screens 1–3, pixel-faithful to the canvas within reason (same layout, tokens, type, states).
- `/journal` and `/research` render the v1 stubs (list view; gate checklist on bot page).
- Phone layout per §6 of the design spec.
- Kill/flatten confirm modals implement the typed-word flow.
- Stale-data badge when last fetch > 60 s.
- Lighthouse accessibility ≥ 95 on each route; keyboard-only operation of KILL ALL possible.

Verify: Playwright smoke test per route loads with seeded data (`scripts/seed_demo.py` creates 5 bots, trades, alerts) and takes screenshots into `var/screens/` for the operator to compare with the canvas. Axe checks pass.

## M5 — Operations (1 day)

Done when:
- `scripts/install_tasks.ps1` registers: server on logon (auto-restart), each bot's cadence tasks, 06:00 digest.
- `scripts/kill_drill.py` runs the kill path against paper bots and writes a controls row "drill"; README documents a monthly drill.
- README covers: install, seeding demo data, adding a bot (manifest + SDK), limits, alerts config, Tailscale phone access (off by default), weekly Schwab re-auth, early-close handling, recovery after a crash (what each control file means).
- Backup: nightly copy of `var/cc.db` to `var/backups/` (7 kept).

Verify: fresh clone on a Windows VM or clean folder → README steps → seeded dashboard visible → kill drill passes → `make test` green.

## Out of scope for this build

Backtest runner, strategy editor, multi-user auth, cloud hosting, brokers other than Schwab, futures/crypto, websockets.

## Order of work and parallelism

M0 → M1 → (M2 ∥ M3) → M4 → M5. M2 and M3 can proceed in parallel after M1 because both depend only on the SDK contract and the schema.
