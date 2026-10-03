# Kickoff prompt for Claude Code

Copy everything below the line into Claude Code, from the repo root, after placing the `docs/` folder,
`CLAUDE.md`, and the existing `spy_mr_bot` folder (as `bots/spy_mr_bot/`) in the repo.

---

You are building the **Trading Bot Command Center**: a local web app that supervises my systematic
trading bots (Schwab, equities and equity options, one Windows PC). The full specification is in this
repo and is the contract for this build:

- `CLAUDE.md` — hard rules and workflow. Read it first and follow it for the entire session.
- `docs/01_PRD.md` — what to build and what not to build.
- `docs/02_ARCHITECTURE.md` — repo layout, data model, the `cc_sdk` contract every bot uses, server, web.
- `docs/03_DESIGN_SPEC.md` — the approved visual design, transcribed from a canvas. Match it.
- `docs/04_BUILD_PLAN.md` — six milestones M0–M5, each with a Verify step.
- `docs/05_ACCEPTANCE_TESTS.md` — the 18 checks I will run myself at the end.

Also in the repo: `bots/spy_mr_bot/`, my working paper-mode bot. Its `strategy.py` is frozen.

## How to work

1. Start by reading all six documents in full. Then write back a short plan: the order you'll take the
   milestones in, any ambiguity you found (with your proposed resolution), and nothing else. Wait for my
   "go" before writing code.
2. Build milestone by milestone, in order. For each milestone:
   - Write the tests named in its Verify step first.
   - Implement until they pass.
   - Run the Verify step and paste the real output (not a description of it) in your summary.
   - Commit as `M<n>: <summary>`.
   - Stop and give me a 5-line status: what's done, what's verified, what's next, any deviation from the
     spec and why, and anything you need from me. Then continue unless I say otherwise.
3. If a spec document and reality conflict (a library doesn't exist, Windows blocks something), do the
   smallest change that preserves the hard rules in `CLAUDE.md`, and record it in a `docs/DECISIONS.md`
   file with date, what, why. Never resolve a conflict by weakening a risk control.
4. Do not invent features. If you think something is missing, add it to `docs/BACKLOG.md` and move on.
5. Plain language in UI copy, commit messages and your reports. No marketing words.

## Definition of done

- All six milestones committed with passing Verify output.
- `make test` green on Windows.
- `python scripts/seed_demo.py` then `make dev` shows the three screens matching `docs/03_DESIGN_SPEC.md`,
  with screenshots saved to `var/screens/` for me to compare against the canvas.
- `bots/spy_mr_bot/` runs through the SDK with `strategy.py` unchanged and the replay test passing.
- `make drill` passes: kill path end to end in under 5 seconds with an audit row written first.
- README lets me install from a fresh clone without asking you anything.
- Every row in `docs/05_ACCEPTANCE_TESTS.md` has been self-checked by you and marked with how you checked it.

## What I care about most, in order

1. A bot can never place an order the risk engine hasn't approved, even if the server is down.
2. Silence shows as failure within 10 minutes.
3. The kill switch works and is audited.
4. The live-vs-backtest view is honest: drift is shown as drift.
5. It looks like the design.

Begin with step 1: read, then plan, then wait for "go".
