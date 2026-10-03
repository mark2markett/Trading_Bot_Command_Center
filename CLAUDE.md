# CLAUDE.md — Trading Bot Command Center

Read `docs/01_PRD.md`, `docs/02_ARCHITECTURE.md`, `docs/03_DESIGN_SPEC.md`, `docs/04_BUILD_PLAN.md`
and `docs/05_ACCEPTANCE_TESTS.md` before writing any code. They are the contract. If something in them
is ambiguous, ask once with a concrete proposal; do not silently pick.

## Hard rules

1. **Schwab is the only broker.** Do not add, stub, or mention another broker or data vendor in the order path.
   Free end-of-day data fallbacks are allowed only inside paper mode and only in bots, never in the server.
2. **Risk checks live in `cc_sdk`, in the bot process, and fail closed.** The server never sits in the order path.
   A dead server must never block a risk-reducing order and must never disable risk checks.
3. **Audit before action.** Every control (pause, flatten, kill, re-arm, limit edit) writes a `controls` row
   before any file is written or process triggered.
4. **Do not change trading rules.** `bots/spy_mr_bot/strategy.py` is frozen. Adapting the bot means wrapping,
   not rewriting. A replay test must prove identical decisions.
5. **No secrets in the repo or in the server.** The server never reads bot `.env` files or token contents.
   Token expiry is inferred from file mtime only.
6. **Localhost only by default.** Bind 127.0.0.1. Any remote access is opt-in and documented.
7. **Match the design.** `docs/03_DESIGN_SPEC.md` transcribes an approved canvas. Use its tokens, layout
   and copy rules. Do not introduce a component library, Tailwind, gradients, emoji, or Inter/Roboto.
8. **Plain language in UI copy and in your reports.** Verdicts are sentences a trader would say.

## Workflow

- Follow `docs/04_BUILD_PLAN.md` milestone by milestone. At the end of each milestone: run its Verify step,
  paste the actual output in your summary, commit with message `M<n>: <what>`. Do not start the next
  milestone if the verify step fails.
- Write tests first for `cc_sdk/risk.py` and `cc_server/riskd.py`. These are the parts that lose money
  if wrong.
- Prefer boring technology: FastAPI, SQLite (WAL), React + Vite + TS, uPlot, CSS modules. No ORM; use
  `sqlite3` with small typed helpers. No websockets in v1.
- Python 3.11+, type hints everywhere, `ruff` clean. TypeScript strict. Node 20+.
- Windows is the production OS. Paths via `pathlib`; scheduler via Task Scheduler; scripts in PowerShell
  with a Bash twin for dev on Linux/macOS.
- Keep files small. A module over ~400 lines should be split.
- When you finish a milestone, update `README.md` for anything an operator must know.

## Repo map

See `docs/02_ARCHITECTURE.md §2`. Runtime state lives only under `var/` (git-ignored).

## Definitions

- **Risk-reducing order**: closes or reduces an existing position (sell of a long, buy-to-cover of a short,
  protective stop, closing an options spread). Never blocked by pause or kill.
- **Degraded bot**: missed heartbeat > 10 min past cadence, broker-vs-state mismatch, parity drift, or
  rejected order in the last 24 h.
- **Parity band**: expected range of live metrics given the manifest's backtest stats and trade count so far.

## Commands

```
make dev        # server + web dev
make test       # python + web tests
make seed       # demo data into var/cc.db
make drill      # kill-switch drill against paper bots
```
