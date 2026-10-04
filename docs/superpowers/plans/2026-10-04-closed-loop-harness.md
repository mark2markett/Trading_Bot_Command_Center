# Closed-loop Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task in this session. Do not dispatch agents unless Mark selects that execution method.

**Goal:** Deliver a repeatable sandbox command that exercises actual bot functions, reports assertions and coverage gaps, and verifies isolation.

**Architecture:** A supervisor creates a unique temporary sandbox and launches a guarded paper-only worker. Small helper modules drive existing runners and API routes; a separately owned sandbox server serves the built dashboard. Evidence and screenshots survive cleanup, while synthetic and unavailable checks remain explicitly identified.

**Tech Stack:** Python 3.11+, existing SQLite SDK, FastAPI/uvicorn/httpx, pandas with a parquet engine, Node 20+, existing Playwright/Vitest/Vite.

**Spec:** `docs/superpowers/specs/2026-10-04-closed-loop-design.md` (approved).

## Global Constraints

- Base: `feat/options-m7` at `2783f2eae2657a9d60b37f4ac5053715633ed683`; implementation branch: `test/closed-loop`.
- Sandbox outside the checkout; runtime in `<temporary cc-closed-loop-*>/var`, reports outside that `var` child.
- Supervisor may start without `CC_VAR`; worker must reject unset or unsafe `CC_VAR`, including resolved symlinks/junctions and sibling `bots/`.
- Reject inherited live mode; all sandbox processes run paper-only with explicit `CC_VAR`.
- Sandbox server binds only `127.0.0.1:8586`; never use an existing process on that port or contact port 8585.
- No credential-file reads, credential output, live orders, real alert delivery, scheduled task changes, remote authentication changes, or unrelated repository writes.
- Real strategy rules and production API behavior remain unchanged. Product defects are reported, not hidden by test-specific changes.
- Three outcomes: `PASS`, `FAIL`, `NOT COVERED`; all synthetic inputs are labeled `SYNTHETIC`. Exit 0 only if no FAIL.
- Reports use America/New_York with its actual zone abbreviation. Keep each new helper below 500 lines.
- Optional seed-demo guard is approved as a separate tested commit; kill-drill behavior stays unchanged.
- Stage explicit paths, never `git add -A`; do not merge into main or push into the unrelated GitHub starter repository.

## Review Focus

1. A symlink/junction or relative path resolves into live state: fail before imports that write, directory creation, or database opening.
2. A busy server port returns plausible dashboard data: never treat it as the owned sandbox server and never issue controls to it.
3. A scenario fails after opening a spread: still stop owned processes, close handles, compare fingerprints, and preserve its failure report.
4. An empty/missing history file or zero-trade window: NOT COVERED with searched dates; never call it a replay PASS or replace it with synthetic history.
5. A daily-bot import or server background task writes outside CC_VAR: isolate imported bot files and instrument actual writes without disabling the production checks.

## File Structure

- `scripts/closed_loop.py`: supervisor, guarded worker, ordered checks, exit status, finalization.
- `scripts/closed_loop_guard.py`: sandbox path validation, process environment, read-only live fingerprints.
- `scripts/closed_loop_report.py`: result records, output table/Markdown, before/after evidence, function inventory.
- `scripts/closed_loop_sources.py`: isolated source loading, actual manifests/rules, bounded parquet search, optional data checks.
- `scripts/closed_loop_scenarios.py`: deterministic scripted inputs and actual paper bot lifecycles.
- `scripts/closed_loop_controls.py`: HTTP checks and controls followed by actual runner steps.
- `scripts/closed_loop_server.py`: guarded server entrypoint and audit-before-flag observations.
- `scripts/closed_loop_web.mjs`: local Playwright screenshots and rendered-dashboard assertions.
- `cc_sdk/tests/test_closed_loop_guard.py`, `test_closed_loop_scenarios.py`, `test_closed_loop_runtime.py`: meaningful safety and integration tests.
- `cc_sdk/tests/test_seed_demo_guard.py`: seed-demo protection tests.
- `scripts/seed_demo.py`, `scripts/kill_drill.py`, `README.md`: approved safety guard/doc updates only.

## Task 1: Isolation and Evidence Foundation

**Interfaces**
- `validate_sandbox(repo: Path, cc_var: str | None) -> Path`: rejects unset, live/checkout paths and sibling bot executables; returns resolved safe runtime path without writing.
- `sandbox_env(repo: Path, runtime: Path) -> dict[str, str]`: explicit CC_VAR, paper mode, PYTHONUTF8, os.pathsep-correct PYTHONPATH.
- `fingerprint(live_var: Path) -> dict`: read-only counts/max IDs and logical digests, control listing/hashes; explicit absent status, no Ledger construction.
- `Report.add(name: str, outcome: str, evidence: str, synthetic: bool = False) -> None`; `Report.exit_code -> int`; `Report.write(path: Path) -> None`.

- [x] Prepare test prerequisites in the existing checkout, never a worktree: create a local virtualenv, install `.[dev]` plus the required parquet engine with verification enabled, and run `npm ci` in cc_web using its lockfile. Preserve dependencies and lockfiles; put caches/generated files in ignored paths or outside the repo. Set CC_VAR to a separate test sandbox for baseline suites that import bots during collection, and record baseline results before new behavior is added.
- [x] Write parameterized guard tests: unset/empty CC_VAR, repo root, repo/var, nested checkout path, relative traversal and symlink into checkout all raise before creating any files. A safe external runtime succeeds. A sibling `bots/x/bot.py` causes refusal.
- [x] Write fingerprint tests against a disposable fixture DB: live connection cannot INSERT; fingerprint leaves logical rows unchanged; positions without `id` work; an UPDATE to position qty and a changed control payload alter fingerprints; absent DB is explicitly unavailable.
- [x] Write report tests: one FAIL gives exit 1; NOT COVERED stays distinct and is counted; synthetic rows are marked; Markdown preserves before/after evidence.
- [x] Run `.venv/bin/python -m pytest -q cc_sdk/tests/test_closed_loop_guard.py` on Linux (Windows equivalent uses `.venv\Scripts\python.exe`). Observe failures for the missing helpers, then implement only the interfaces above and rerun to green.

## Task 2: Actual Sources and Offline Strategy Lifecycles

**Interfaces**
- `load_fleet(repo: Path, runtime: Path) -> dict[str, Bot]`: register the five actual paper manifests in one sandbox ledger without opening credential files.
- `make_scenarios(repo: Path, runtime: Path) -> ScenarioContext`: holds bots, real rule objects, deterministic feeds and runners. `ScenarioContext.close() -> None` closes all owned bot ledger handles.
- `run_offline(context: ScenarioContext, report: Report) -> None`: tests actual intraday equity, options and daily-paper lifecycles with explicit synthetic labels.

- [x] Add a test that source loading creates exactly `{gap_go, nr7, sip_orb, spy_mr, gap_go_spread}` and leaves source directories unchanged. Copy only tracked Python source needed for side-effectful daily-bot loading into sandbox `imports/`, never `<sandbox>/bots/`, dotenv files, or live state.
- [x] Add synthetic gap-go and NR7/SIP cases that the actual rules accept, run real SessionRunner entry and exit, and assert orders, fills, trades and flat positions. Assert a no-signal fixture makes no entry.
- [x] Add a spread case using actual GapGoRules and the real manifest: after entry, two signed OCC positions and optlive Greeks exist; after flatten, positions and optlive are gone and option_trades persists. Add stale-chain and excessive-premium cases that assert actual persisted refusals.
- [x] Adapt the existing daily-MR lifecycle fixture to valid dates and isolated imports. Call real `cmd_decide`/`cmd_reconcile` with PaperBroker and sandbox state; assert entry, protective stop, exit and SDK ledger writes. Label synthetic calendar/input adaptations; do not report a scheduled/live run as covered.
- [x] Run `.venv/bin/python -m pytest -q cc_sdk/tests/test_closed_loop_scenarios.py`; observe missing behavior failures, implement sources/scenarios, then verify all new cases pass without strategy edits.

## Task 3: Real-History Replay and Honest Coverage

**Interfaces**
- `replay_history(context: ScenarioContext, repo: Path, report: Report, max_days: int = 250) -> None`: uses actual `run_replay` into the sandbox and preserves original source data.
- `check_data(context: ScenarioContext, report: Report) -> None`: presence-only injected configuration check; counts/ages from allowed read-only SDK operations; otherwise precise NOT COVERED.

- [x] Test missing data, unreadable/corrupt parquet and a zero-trade window separately: missing and valid no-signal windows are NOT COVERED; invalid available data is a FAIL with a safe diagnostic. Verify the search bound is 250 trading days, not calendar days.
- [x] Test an available controlled parquet fixture through actual run_replay: require orders + fills + a closed trade and assert source file bytes are unchanged. This fixture is synthetic and must never produce a real-history PASS label.
- [x] Prepare only needed historical bars in sandbox/data, retaining 40 prior daily contexts. Bound attempts, restore ledger clock in finally, and distinguish an absent setup from a triggered signal that fails unexpectedly.
- [x] Test missing injected auth variables without touching dotenv/token files. Errors report exception class or fixed safe messages, never raw authenticated responses/URLs. Do not invent or request credentials to make cloud checks pass.
- [x] Run targeted source/replay tests, implement replay/data checks, then rerun to green. Report real-history coverage as unavailable in the current cloud bundle.

## Task 4: Sandbox Dashboard and Controls

**Interfaces**
- `start_server(repo: Path, runtime: Path) -> OwnedServer`: fail if port 8586 is already in use, launch guarded child, require matching run identity and expected fleet before controls. `OwnedServer.stop() -> None` stops only that child, with bounded wait/kill fallback.
- `check_dashboard(context: ScenarioContext, server: OwnedServer, report: Report) -> None`.
- `check_controls(context: ScenarioContext, server: OwnedServer, report: Report) -> None`.

- [x] Write busy-port and wrong-identity tests: a listening unrelated server produces refusal; no control HTTP call reaches it.
- [x] Start the actual FastAPI application via the guarded wrapper, observe actual Control.write_flag calls, and append sandbox evidence that the matching control audit row existed before each server flag write. Do not replace the control handler, risk engine, or flag write itself.
- [x] Assert fleet contains exactly five actual IDs, recent fills and expected trades; spread detail/fleet have numeric delta, theta and DTE; health/risk/alerts/research respond with the expected shape.
- [x] Drive invalid confirmation, bot pause/resume/flatten/kill, fleet pause/resume/flatten/kill/re-arm using exact API bodies. After each control, step actual runners and assert flags, audits, fills, exits, rejected entries, and status readback. Use independent entry attempts where duplicate/day limits would otherwise obscure the intended check.
- [x] Assert flatten writes an option_trades row and removes optlive; kill permits exits and blocks entries; re-arm removes KILL and restores an otherwise-eligible SDK entry. Check rejection attention items using existing API guarantees.
- [x] Add Playwright script taking explicit local base URL and output directory. Require rendered fleet/spread content and no failed core API responses before taking the two screenshots. Missing browser is NOT COVERED; a launched browser with wrong UI behavior is FAIL.
- [x] Run runtime integration tests red, implement controls/server/screenshot helpers, then rerun to green. Keep production port 8585 unused.

## Task 5: Supervisor, Cleanup and Function Coverage Report

**Interfaces**
- `main(argv: list[str] | None = None) -> int` in `scripts/closed_loop.py`: supervisor by default; internal worker mode validates its environment before importing side-effectful modules.
- Function inventory: list actual SDK/server/bot callable locations; record which the harness reaches and which scenarios assert their outcomes. Distinguish an observed call from an asserted behavior; unexercised functions remain explicit gaps.

- [x] Test default launcher creation with unset CC_VAR, unsafe caller refusal, inherited MODE=live refusal and worker refusal with unset CC_VAR. Assert the supervisor passes the exact external CC_VAR and paper mode to each child.
- [x] Test a deliberate failed check after opening a spread: retain a FAIL row, nonzero exit, report, before/after evidence, and screenshots already produced; stop the owned server and delete sandbox runtime state after all handles close.
- [x] Test cleanup failure and interrupted-worker paths: never silently return success, never delete a caller directory or live source, and preserve evidence. If state cannot be safely deleted, report the remaining external sandbox path.
- [x] Test function inventory reports an uncalled function as unexercised rather than claiming full coverage. Preserve separate unsupported scheduled/live/authentication paths.
- [x] Implement coordinator, bounded worker lifecycle, per-row diagnostics, finally cleanup and Markdown summary. Run targeted runtime/guard tests to green and exercise the documented single command.

## Task 6: Approved Demo-Seeding Guard, Separate Commit

**Interfaces**
- Preserve `main(reset: bool)` compatibility while adding `main(reset: bool, *, live_ledger: bool = False) -> None` in seed_demo. CLI accepts `--live-ledger` as an explicit override; guard runs before reset/unlink/Ledger construction.

- [x] Add tests that unset and checkout-contained CC_VAR reject before touching a sentinel live fixture DB; `--reset` cannot bypass the guard. A safe external sandbox permits seeding. Cover resolved symlinks and the explicit live override using only disposable fixture paths.
- [x] Run `.venv/bin/python -m pytest -q cc_sdk/tests/test_seed_demo_guard.py` and observe that current seed_demo does not refuse unsafe paths. Implement the guard, rerun to green, and document kill_drill's existing live-ledger behavior without changing its execution.
- [x] Commit only the safety helper if shared, `scripts/seed_demo.py`, `scripts/kill_drill.py`, and its tests under a separate message: `fix: require explicit live-ledger demo seeding`.

## Task 7: Full Verification and Portable Handoff

- [ ] Reuse the validated test prerequisites from Task 1. Keep CC_VAR pointed at a separate test sandbox for the existing suites, which may import bots during collection.
- [ ] Run full `.venv/bin/python -m pytest -q` from the repository root; record executed/pass/fail/skip counts. Investigate every failure and distinguish pre-existing defects from harness changes.
- [ ] Run `npm test -- --run` and `npm run build` in cc_web; record results. If the selected Playwright browser is unavailable, use its supported verified installation, then run screenshot checks; otherwise report the concrete external blocker.
- [ ] Run `ruff check` on new/changed Python helpers and tests; run `git diff --check`. Run the harness after the built dashboard exists, verifying the actual report and retained screenshot paths. Run it again to check repeatability and ensure no sandbox process remains.
- [ ] Update README with Windows/Linux commands, safety behavior, optional-data prerequisites, report interpretation, and local follow-up. Save only tested environment installation/startup instructions if needed; do not replace environment repository membership with an origin-less bundle checkout.
- [ ] Commit harness files, tests and docs by explicit paths. Confirm a clean test/closed-loop branch, no strategy edits, and no changes to the separate GitHub checkout.
- [ ] Produce an incremental Git bundle containing `test/closed-loop` beyond `2783f2e` and a standalone report for transfer. Document importing into Mark's local repo while preserving his current branch, intentional changes and live var data. Never claim cloud results verify the Windows live ledger.

## Execution Review

This plan implements the approved design and all handoff rows, including accurate unavailable-data outcomes. It includes the five review-focus cases in their owning tasks. Native execution in this session is recommended because the source loading, scenario state, controls, and cleanup interfaces are tightly coupled; a single implementer can keep those boundaries consistent. Independent agent execution remains an owner choice.
