# Native completion: Command Center valuation and SIP scanner

This is a handoff reference for the user's instruction to complete both repairs without unnecessary approval pauses. It does not replace the user's instructions, actual repository governance, tool permissions, or required release checks. Read FINISH-CC-FIXES.md, SERVER-IMPORT-FIX.md and the current repositories before acting. Distinguish completed source work from observed native/production readiness.

## Goal and existing authorization

Complete the two requested incident repairs: native server paper-account valuation and the existing paper SIP ORB strategy's scanner connection. The user authorized fixing both and asked to continue through the processes without stopping between routine steps. Reuse that authorization; do not ask again to run read-only diagnostics, install the reviewed server repair, publish bounded corrections or configure the specified scanner connection. Follow required current-head GitHub review/checks and canonical release authority. A new material release critique or unavailable credential is a real prerequisite, not permission to bypass a gate.

## Native repository and invariants

- Root: C:\Users\Administrator\trading_bots\command-center. Native latest is **feat/options-m7**, not main. Inspect current HEAD/status first; preserve intentional bot.log, scripts/dev.sh and handoff changes.
- Native Python: .venv\Scripts\python.exe. The scheduled bots use the checked-out source. Do not switch/reset the active branch, force-stop bots, start duplicate sessions, seed fabricated quotes, reset P&L/capital or clear risk controls.
- One shared **$100,000 paper account** was already initialized. All five strategies remain paper; this task grants no LIVE promotion or broker-order authority.
- The October 7 10:05-10:07 ET snapshot had an open NR7 paper SPY position. It is historical: inspect current positions/heartbeats and preserve exit management rather than assuming that position is still open.
- Server API: http://127.0.0.1:8585. The latest cloud-only snapshot cannot establish its current native state.

## Available verified repairs

All adjacent transfer payloads are covered by SHA256.txt. Use only the current reviewed helpers, not the historical whole-runtime installers.

1. **Server import repair 54390e0f13a50c540188b04ec23efb2bbe8287e2.** The scheduled root launch resolved the outer SDK namespace instead of its initializer, so first-position SchwabFeed import failed on Bot/Order exports. main.py now prepends the actual SDK source root before application imports. Fresh-process real-feed-parser/paper-valuation regression failed before the fix and passed after. All **236 Python tests** and scoped Ruff passed. APPLY-SERVER-IMPORT-FIX.ps1 checks a two-file allowlist, cherry-picks the single repair, runs only the isolated startup test and restarts only CC server. It preserves bot sessions and polls actual paper-account readiness. Diagnose real feed errors if paper_account.ready stays false; do not fake success with account resets or marks.

2. **Scanner feature de30dff23e5b017d27b750be027d10adbe25641c**, published and advertised ref verified on mark2markett/m2m-platform, feat/cc-sip-scanner. PR #1260 targets main. The feature integrates platform main **803f29dcf2ae69134f3a4998c771843a0c9f7f4a**, preserving the daytime-read and strict interpreter repairs. Production build, full Node20 suite (**9,218 passed, 1 expected fail, 13 skipped, 11 todo**), 120 focused scanner/registry tests, acceptance verifier and repository gates passed. Local read-only review found no blockers; it is not required GitHub approval.

3. **CONFIGURE-SIP-SCANNER.py**, adjacent to this handoff. Its 17 tests and independent review passed. It verifies an authenticated private/no-store current-session machine response before atomically writing only SCANNER_URL, SCANNER_SECRET and blank SIP_SYMBOLS to the untracked Git-ignored bots/sip_orb/.env.local. It preserves other settings, rejects dotenv substitution syntax and checks exact secret round-trip. Interactive secret input is hidden; do not pass credentials as CLI arguments or include them in logs/chat. If you automate with an already authorized secure in-memory secret, reuse configure(repo, secret) rather than duplicating its checks or writing values to temporary public files.

## Continue in this order

1. Inspect native status and install/confirm the server-only repair. Run its helper from this transfer folder; verify current API/risk freshness, paper_account.ready and existing bot sessions after the server restart. If already installed, inspect/test its import context and only restart the server if needed to load the fix.
2. Use native working GitHub CLI access to update PR #1260's description from SCANNER-PULL-REQUEST.md, preserving its previous body. PUBLISH-PLATFORM-SCANNER.ps1 -UpdatePullRequestBody already does this in an isolated temporary platform checkout. Confirm remote PR head, watch current-head checks, inspect the actual Codex critique and run the canonical delivery readiness verifier as appropriate. Complete review corrections on the feature branch if needed, with meaningful regressions and required new review/check runs. Preserve latest main changes. Do not override aggregate statuses, weaken identity/auth guards, ignore a red publisher or treat a preview as production.
3. Complete owner-controlled release under actual current CLAUDE.md and D-021 governance. Only the reviewed/approved main release is the production source. Use the existing authorized Vercel connection/CLI if available; identify the **existing project serving www.mark2markets.com**, never create an accidental replacement project. Cloud GitHub API requests and the public production probe were blocked, so there is no verified current check/deployment result in this handoff.
4. Configure a distinct dedicated random SIP_SCANNER_SECRET securely, preserving existing production OAuth/Supabase/Redis/CRON bindings. Set SIP_SCANNER_ENABLED=true for the operating morning before 09:00 ET. Release with these production settings and verify the production deployment is READY, tied to the actual owner-merged commit and assigned to the domain. Environment updates alone do not alter an existing deployed artifact. If existing management authentication is absent, use its supported secure login/input flow; do not invent or expose credentials.
5. Save the same dedicated secret and canonical scanner URL using CONFIGURE-SIP-SCANNER.py after the deployed endpoint responds correctly. Its authenticated 202 is acceptable for configuration when today's scan is absent; it does not prove history coverage or a fresh trading universe. Do not restart late to manufacture a missed opening scan. Confirm native configuration-only readiness and existing enabled schedules without changing their trading times.
6. Arrange/observe the next timely morning check on **Thursday October 8, 09:35-09:39 Eastern** using scripts/native_readiness.py. Production preparation is scheduled at 09:00-09:25 and publication at 09:35-09:39 through the existing minute dispatcher. A future scheduled verification is useful but is not proof it has already passed. Report any live provider/history/storage failures with bounded logs and actual evidence. SIP's deadline remains 09:40; retain exit management. A valid empty candidate list is a successful scan, not a reason for fallback trades.

## Required completion evidence

- Native startup/import repair installed and actual fresh risk/valuation readiness observed; bot position/exit management preserved.
- Scanner current-head mandatory GitHub checks/review passed and owner release follows canonical governance; READY production artifact is tied to merged main and the correct domain.
- Native and production scanner settings securely matched; configuration check passed without replacing existing feed credentials.
- Actual timely scheduled preparation/publication, authenticated fresh v1 snapshot and native selected-universe evidence observed. If the next opening window has not occurred, label this evidence pending and carry the task forward.

Keep working through ordinary next steps instead of ending after a passing command. Stop dependent work only for a concrete missing credential, tool restriction, required unresolved owner verdict or future market window; complete independent work meanwhile and state the exact remaining prerequisite. Do not claim both issues operationally resolved while these observations are missing.
