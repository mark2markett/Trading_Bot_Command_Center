## Outcome and acceptance

Delivery requirements: R00
Acceptance plan: docs/delivery/plans/R00-cc-sip-scanner.json
Closes gate: NONE — bounded restoration of the existing Command Center paper SIP ORB scanner input; no historical gate row is changed.

SIP ORB currently has no scanner source. This change supplies its existing universe contract from the platform's verified stock universe and shared Schwab data, using the existing minute dispatcher. It prepares before the open and publishes a frozen ranked snapshot after the five-minute opening window. Missing history, provider/storage failures, stale data and a valid empty result are distinct outcomes. Machine reads require a dedicated secret; the feature is disabled unless explicitly enabled.

## Validation

The source at e8146e8 passed the complete local platform suite: 9050 passed, 1 expected failure, 13 skipped and 11 todo. Its production build also passed. Fresh release checks passed 52 scanner/dispatcher tests and 34 production-boundary tests, TypeScript checks, cron-manifest checks and control-plane registry checks. The acceptance-plan schema and requirement coverage passed. The added acceptance plan changes no application code.

The branch has a clean merge with main e8d193c3. These are local results, not GitHub review, deployment, live provider or native scheduler certification. No production credentials were used by the tests.

## Independent review and release

The separate GitHub Codex adversarial review and all required checks must pass on the current head before owner merge. Run `node scripts/delivery-gate.mjs readiness <PR-number>` from that head and inspect the Vercel preview check too. Only Mark merges under D-021/D-031; this authoring session has not self-cleared release.

After merge, confirm the production deployment is READY and configure the dedicated scanner secret, existing Schwab/Redis inputs and enabled flag through secure deployment settings. Verify a fresh authenticated snapshot at 09:35–09:39 Eastern. Configuration details: docs/runbooks/CC-SIP-SCANNER.md. Do not place credential values in the PR.

## Plan and GATES impact

The new R00 plan covers the bounded integration. It does not change requirement outcomes/criteria, GATES history, CURRENT-STATE completion records, DECISIONS or trading authority. No product completion or live-readiness claim is recorded. The native shared $100,000 paper account repair is a separate Command Center change.

## Risks and rollback

Shared provider quota and real 14-session opening-window coverage still need live observation. Redis is required; there is no in-memory substitute. Calendar coverage is 2026–2027 and fails closed outside that range. Disable SIP_SCANNER_ENABLED to stop production and refuse scanner reads, or revert this PR to remove the logical job and endpoints. The native client continues exit management when scanner input is unavailable. No orders or database migrations are introduced.
