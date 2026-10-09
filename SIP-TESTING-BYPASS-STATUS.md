# SIP four-stock paper test window

PR: https://github.com/mark2markett/m2m-platform/pull/1280
Branch: fix/sip-testing-four-exclusions
Reviewed head: e24a29fbf42ac60b8ef4917384ebbd5cf9d9c8f1

Owner-approved exclusions: BRK.B, EA, SATS, WBD only. Active Eastern session dates October 9 through October 13, 2026; scheduled paper sessions October 9, 12 and 13. On October 14 normal validation resumes. Exclusions remain explicit in preparation/publication evidence. Other data, authentication, storage and quote checks remain active.

130 focused SIP tests passed on this head. The updated October 9 publication fixture passed through the actual native parser/rules/risk/paper runner: AMD and NVDA selected, two closed trades and four fills, with disposable SQLite and closed handles. This is synthetic evidence, not live provider or Windows readiness.

Final GitHub Codex review: APPROVE_WITH_CONCERNS, no blockers:
https://github.com/mark2markett/m2m-platform/pull/1280#issuecomment-6071492853

Review disposition:
- C-1: The only production SipScanner caller is the dedicated cc-sip-scanner cron route. The authorized native fleet is five paper bots, and native readiness checks that mode. No other platform scanner or live bot is changed. Explicit context gating for hypothetical future reuse remains a concern for owner acknowledgement rather than a new configuration requirement in this bounded maintenance.
- C-2: Production session dates come from calendar.clock. Every syntactically valid date between the hard-coded October 9 and October 13 bounds is calendar-valid; malformed shapes and dates outside the window do not activate exclusions. Non-trading publication times are refused by phaseAt. The review concern about a future generalized date range remains recorded.
- C-3: Duplicate cached exclusions are refused by the existing strict snapshot validator and never published or silently deduplicated. This can occur after provider reads; failing earlier would save those reads in a corrupted-cache case, but does not change the fail-closed result. A regression proves refusal and retention of the original evidence.

Full local parallel verification on this head: 9,327 passed, two 10-second scan timeouts, one expected failure, 13 skipped, 11 todo; 965 test files (958 passed, two failed, five skipped). Timeout tests: src/lib/curator/__tests__/boundaryGate.test.ts / ALLOWS a BARE first-party specifier to a PERMITTED module; src/lib/security/__tests__/tradeExecutionInsertLineage.test.ts / excludes transient boundaryGate fixtures from the inventory scan. The complete final-head serial rerun passed: 9,329 passed, one expected failure, 13 skipped, 11 todo; 960 files passed and five skipped. The same final-head GitHub quality workflow completed successfully, including the full unit suite, production build and required validation gates. No assertions, inventory or timeouts were weakened.

All required current-head GitHub checks and the Vercel preview passed; PR merge state is CLEAN. The canonical readiness CLI reached the live main branch-protection read, but the cloud GitHub integration lacks Administration read permission (HTTP 403: Resource not accessible by integration). That check must run under the native owner account before merge. Release remains pending Mark's owner merge under CLAUDE.md rules 19/20/26/27. Production is unchanged by this PR so far. No Windows code installation is needed for this upstream-only change. Owner merge triggers the existing deployment flow; deployed commit and actual morning publication still need verification.

For each test morning: a fresh authenticated current-session snapshot at 09:35–09:39 Eastern, four recorded testing exclusions when present in the starting universe, native scanner selection and a successful SIP heartbeat. Keep daily ledger backups and monitor reports; only observed complete runs count as successful end-to-end days. The remaining 38 partial gaps in the October 8 broad-universe diagnostic are not automatically excluded and may still block publication if eligible.

Before Monday October 12: confirm/renew existing shared Schwab authorization. The latest October 8 screenshot showed two days remaining. Existing platform connection page: /trades/schwab-reauth; use the existing scope/connection and keep credentials in the native browser flow.

Prepared native owner script: COMPLETE-SIP-TEST-WINDOW.ps1. It pins the reviewed head, verifies Mark identity, runs the existing canonical readiness helper with the owner CLI credential, restores the prior environment token, and invokes a normal head-pinned squash merge only on readiness success. It has not been executed in this Linux cloud environment; PowerShell is unavailable here. No admin bypass, force push, native bot installation or capital/control changes are included.
