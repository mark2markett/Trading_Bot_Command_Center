# SIP four-stock paper test window

PR: https://github.com/mark2markett/m2m-platform/pull/1280
Branch: fix/sip-testing-four-exclusions
Release head: 88967dc555ba4c5cd938dde04638c12983b6b75d
Integrated main: e287d7f35118e0deb4d5f383d6412a46e5d004eb

The previous native owner command passed canonical readiness, including enforced strict branch protection, but the merge failed after main advanced. The conflict was confined to CHANGELOG. Both sides' entries are retained; scanner code, fixtures and dependencies are identical to the previously reviewed e24a29fb head. GitHub now reports the updated branch MERGEABLE. Fresh release checks and independent review are required on this new head before release.

Scope: bypass exactly BRK.B, EA, SATS and WBD in the dedicated Command Center SIP scanner for Eastern session dates October 9–13, 2026 (scheduled sessions October 9, 12 and 13). Record TESTING_OPENING_DATA_UNAVAILABLE for each exclusion. Normal validation resumes October 14. No broader universe, signals, exits, risk, capital, controls or Windows schedule changes. Already-published valid snapshots remain immutable; other incomplete windows and provider/auth/storage failures remain blocking.

Fresh local verification: 130 SIP tests passed and source typecheck passed on 88967dc5. No source changes beyond the current main integration were made to the scanner. The previous native parser/rules/risk/paper-runner fixture proof selected AMD/NVDA only, closed two trades and recorded four fills in disposable SQLite; that is synthetic evidence, not a live morning pass.

Current-head acceptance and Vercel preview passed. Independent Codex review returned APPROVE_WITH_CONCERNS, no blockers:
https://github.com/mark2markett/m2m-platform/pull/1280#issuecomment-6079737534
All required current-head checks passed; PR merge state is CLEAN and mergeability is MERGEABLE. Quality passed the complete unit suite, production build and validation gates. Verified successful pull_request_target workflows on this head: quality 37922092840, delivery-acceptance 37922092732, Codex review 37922093016. Production activation is pending owner merge and verification of the resulting production deployment.

Review disposition for owner acknowledgement:
- C-1: Duplicate cached testing exclusions are refused by strict snapshot validation and never saved or silently deduplicated. Detection happens after provider reads, which wastes reads in a corrupted-cache case; the existing regression proves refusal and preservation of original evidence. Earlier rejection remains an optimization, not a publication bypass.
- C-2: Production clock dates are canonical ISO dates. testingBypassActive enforces ISO shape and the fixed October 9–13 range; every date in that range is calendar-valid. Non-trading publication is separately refused by phaseAt. A generalized future date range would need stronger calendar handling.
- N-1: A shared exclusion-reason constant is optional cleanup. No reason or enum contract changed in this conflict repair.

Owner command: COMPLETE-SIP-TEST-WINDOW.ps1. It pins the release head, checks Mark identity and PR mergeability, runs canonical readiness under the owner CLI credential, restores the prior environment token, and invokes a normal head-pinned squash merge. No admin bypass or force push. The cloud integration lacks Administration read for canonical branch protection and cannot replace the owner's native verification. The previous command ran successfully through canonical readiness on Windows; the updated mergeability guard has not been executed on Windows here.

Morning evidence needed to count a clean day: fresh authenticated current-session scanner publication at 09:35–09:39 Eastern, explicit testing exclusions when present in the starting universe, native scanner selection and a successful SIP heartbeat. Keep ledger backups and monitor reports. Other partial gaps among the 38 stocks in the October 8 diagnostic may still block publication if eligible; this bypass is not proof of complete provider coverage. Do not restart SIP late to bypass the entry deadline.

Before Monday October 12, confirm/renew the existing shared Schwab authorization through /trades/schwab-reauth. The October 8 screenshot showed two days remaining; keep credentials in the native browser flow.
