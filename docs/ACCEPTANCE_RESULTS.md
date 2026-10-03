# Acceptance self-check

Run by the builder on 2026-10-03. 'partial' means the mechanism exists and is unit-tested but the operator-facing step was not exercised in the build environment.

| # | Scenario | Result | How checked |
|---|---|---|---|
| A1 | Cold start | pass | Fresh clone build + server start verified in this environment; empty-fleet state renders 'No bots yet'. |
| A2 | Seeded fleet | pass | scripts/seed_demo.py: 5 bots, QQQ degraded first, correlation flag qqq_mr/spy_mr 0.80 with sentence. var/screens/fleet.png |
| A3 | Real bot joins | pass | bots/spy_mr_bot reconcile registered 'spy_mr' with a heartbeat (failed here because the sandbox blocks market data; that failure shows as degraded, as designed). |
| A4 | Rules untouched | pass | git diff pre-m2 -- bots/spy_mr_bot/strategy.py is empty; tests/test_strategy_file_frozen pins sha256; replay parity test passes. |
| A5 | Fat-finger rejected | pass | cc_sdk/tests/test_risk.py::test_fat_finger_rejected_with_alert_severity; no broker call is possible because rejection returns before send(). |
| A6 | Kill drill | pass | cc_server/tests/test_kill_path.py + scripts/kill_drill.py: audit row precedes flag, flatten flags, page alert, fleet shows KILLED, 0.05 s. |
| A7 | Re-arm | pass | test_kill_path: rearm removes KILL, fleet.killed false, controls row 'rearm'. |
| A8 | Pause keeps exits | pass | test_risk::test_pause_blocks_entry_allows_exit and test_kill_blocks_entry_allows_stop. |
| A9 | Silence is failure | pass | test_kill_path::test_silence_is_failure: degraded at due+10min, paged once, not before grace. |
| A10 | Drawdown ladder | pass | test_kill_path::test_drawdown_ladder: pause at -6.5%, flatten at -8.5%, kill at -11%, each once, all audited. |
| A11 | Parity drift | pass | test_kill_path::test_parity_drift_and_limit_audit: 4/12 wins vs 73% -> 'drift', sentence 'win rate 33% vs 73%'; seed shows 42% vs 73% in UI. |
| A12 | Limit edit audited | pass | same test: before 0.02 -> after 0.025 in audit; UI edit requires a note. |
| A13 | Token warning | partial | riskd.token_watch pages once/day under 2 days from token mtime; header chip colors at <4/<2 days. Not exercised end-to-end here (no token file in sandbox). |
| A14 | Early close | partial | calendar + riskd.early_close_notice post the digest item the day before; decide-time change is a manual step documented in README (BACKLOG). |
| A15 | Server down, bot safe | pass | Risk engine is in-process (cc_sdk); test_risk runs with no server. Missing control dir fails closed (test_missing_control_dir_fails_closed). |
| A16 | Phone | pass | e2e 'fleet phone layout': KILL ALL visible, height >= 44px, cards replace table. var/screens/fleet-phone.png |
| A17 | Accessibility | partial | Keyboard path to KILL ALL and modal verified by e2e; real buttons/links and aria labels used; axe not run in this environment. |
| A18 | No secrets | pass | git grep over tracked files finds names only; var/, .env, *token*.json ignored. |
