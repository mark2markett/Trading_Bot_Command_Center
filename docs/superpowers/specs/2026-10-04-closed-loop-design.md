# Closed-loop harness design

Status: proposed for owner review. No harness implementation has begun.

## Purpose and source

Mark requested a closed-loop harness to test the functions of the existing
trading bots. The code base is the uploaded local repository, not the separate
GitHub starter repository. The verified base is `feat/options-m7` at
`2783f2eae2657a9d60b37f4ac5053715633ed683`; work is on `test/closed-loop`.

The supplied `CODEX-CLOSED-LOOP-TEST-PROMPT-2026-10-04.md` describes the desired
checks. It is supporting requirements, not permission to alter running bots,
send notifications, access unrelated systems, or place live orders.

Success means one repeatable command exercises actual strategy, risk, paper
fill, ledger, dashboard API, and control code; reports evidence and coverage
gaps; and leaves the live record unchanged when run on the trading PC.

## Command and sandbox boundary

Windows: `.venv\Scripts\python.exe scripts\closed_loop.py`.
Linux: `.venv/bin/python scripts/closed_loop.py`.

The command is a supervisor. It creates a unique `cc-closed-loop-*` directory
under the system temporary directory, outside the checkout. Reports and
screenshots live in that directory; runtime state lives in its `var/` child.

**Proposed resolution of a handoff ambiguity:** the supervisor can start with
`CC_VAR` unset so the advertised one-command workflow works. It sets `CC_VAR`
to the generated sandbox before launching a worker. The worker refuses to
start with `CC_VAR` unset, inside the checkout, equal to the live var directory,
or with a sibling `bots/` directory. An explicitly supplied unsafe `CC_VAR`
also makes the supervisor refuse before writing anything. Validate resolved
paths, including symlinks/junctions, rather than string prefixes.

Every bot and server process receives the same validated `CC_VAR` and paper
mode. Reject inherited live mode. Never run scheduled bot CLI commands or
reuse an existing server on port 8586. Start only the sandbox server on
`127.0.0.1:8586`; never contact port 8585. Server controls cannot discover actual
bot executables through `<sandbox>/bots/`.

Do not read `.env`, `.env.local`, token files, or alert configuration. Do not
copy live alerts, state, tokens, or databases. No live broker, scheduler,
Vercel, Supabase, or other repository changes. Subprocess errors and reports
must not expose credential values or raw authenticated HTTP responses.

## Actual code to exercise

Use `SessionRunner`, `SpreadSessionRunner`, `Risk`, `Ledger`, and the existing
FastAPI routes. Preserve all strategy rules and production API behavior.

Register the five actual manifests in the sandbox: `gap_go`, `nr7`, `sip_orb`,
`spy_mr`, and `gap_go_spread`. Load configuration without executing existing
entrypoint side effects such as dotenv loading or writes to `bot.log`.

Use real `GapGoRules` for the synthetic options scenario, not the always-enter
test rule from `test_options_runner.py`. Use deterministic bars and chain
quotes to trigger its actual gap/range conditions. Every synthetic result is
labeled `SYNTHETIC`, including synthetic equity or daily-bot scenarios.

The runner loop is inputs -> strategy -> risk -> paper fills -> ledger -> API
readback -> API control -> next runner step -> ledger and API assertions.

## Coverage and evidence

1. **Live fingerprint before:** when `<repo>/var/cc.db` exists, open it through
   a read-only SQLite connection and snapshot counts and maximum IDs for the
   specified tables. `positions` has no `id`: report its count and a logical
   content digest instead. Include a control-directory listing and content
   hashes. Exclude heartbeats and kv as the handoff permits. Missing live
   state is `NOT COVERED`, never proof that the Windows ledger was untouched.
2. **Real data connection:** inspect only injected variable names/presence.
   Check live data only where the SDK can do so without reading credential
   files or changing remote authentication state. Otherwise report the
   exact missing prerequisite as `NOT COVERED`. Print counts and quote ages
   only; market-closed staleness is not itself a failure.
3. **Historical gap_go and nr7:** read local parquet data only when available.
   Bound the search to 250 trading days, retain enough prior bars for context,
   and use `run_replay` with a sandbox Bot. Data needed by its `var_dir()` path
   is prepared only under sandbox `data/`. Require actual orders, fills, and
   closed trades. Report a searched window with no qualifying signal as
   `NOT COVERED`, distinct from a signal blocked by an unexplained failure.
4. **Other strategies:** exercise offline portions of SIP ORB and daily MR
   using real rules and isolated adapters where possible. Report external
   scanner, scheduled lifecycle, and live-data gaps individually. Do not
   claim that passing a pure rule test covers a scheduled bot lifecycle.
5. **Options:** open an actual paper debit spread with scripted bars/chain,
   verify its leg positions, fills, and `optlive:` row, leave it open for API
   checks, and assert delta, theta, and DTE in fleet and bot-detail responses.
6. **Dashboard:** start the sandbox server, require exactly the five bot IDs,
   validate trade and recent-fill readback, and assert health/risk/alerts/
   research route responses. Capture fleet and spread-detail screenshots
   using the built web app and Playwright if the browser is available.
7. **Controls:** test invalid and valid confirmations; bot pause/resume,
   flatten, kill; fleet pause/resume, flatten, kill, re-arm. Verify audit rows
   before flag writes using observation around actual server flag writes,
   then verify runner behavior and persisted state. The runner suppresses
   entries before calling risk when paused: distinguish this from an
   explicit SDK entry attempt that records a rejection containing `pause`.
   Exits remain allowed. A spread flatten removes `optlive:` and creates an
   `option_trades` row. Kill flattens open positions on the next step, blocks
   new entries, and re-arm restores eligibility.
8. **Refusals:** oversized share order, excessive option premium, and stale
   chain must be rejected by actual risk/fill code. Assert persisted
   rejection/decision evidence and attention items where the existing API
   promises them. Do not change product behavior to make an assertion pass.
9. **After and cleanup:** repeat the live fingerprint and compare side by
   side. Unexpected differences are `FAIL`, with concurrent live activity
   identified as a possible cause rather than silently accepted. Stop only
   the owned sandbox server; close all SQLite handles before deleting runtime
   state. Preserve reports/screenshots even after a failure.

Each row is `PASS`, `FAIL`, or `NOT COVERED`, with evidence. Exit zero only
when there are no failures; make coverage gaps prominent in the summary.
Dates/times in reports use America/New_York with the actual zone abbreviation.

## Cloud validation limits

The bundle contains tracked source and history only. It has no live ledger,
parquet history, credentials, or Windows scheduled tasks. Cloud verification
can exercise synthetic scenarios against the actual code and run existing
Python/web suites and build. The report must reserve Windows live-state,
historical replay, real feed, and scheduler claims for a later local run.

## Deliverables and change scope

Add `scripts/closed_loop.py` and small helper modules under `scripts/`, each
under 500 lines. Add focused tests under the configured `cc_sdk/tests/` tree
for unsafe paths, unset worker environment, live mode, lifecycle assertions,
failed-report exit status, and failure cleanup. Update README instructions.

The handoff's optional `seed_demo.py` safety change is outside the harness
itself. Proposed default: include it as a separate tested commit, requiring
an external sandbox unless an explicit `--live-ledger` flag is supplied.
Only document the live-ledger behavior of `kill_drill.py`; do not change it.
Any other production defect discovered by the harness is reported first;
a fix needs its own reproducing test and separate commit.

Run the full Python suite, web Vitest suite, web build, and the harness.
Record actual test counts; do not assume the handoff's expected 93 tests.
Commit on `test/closed-loop`; never merge into `main`. Return a Git bundle or
patch for Mark's local repository, which has no remote. Do not push this code
to the separate GitHub starter repository.
