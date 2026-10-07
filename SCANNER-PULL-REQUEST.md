## Outcome and acceptance

Delivery requirements: R00
Acceptance plan: docs/delivery/plans/R00-cc-sip-scanner.json
Closes gate: NONE — bounded restoration of the existing Command Center paper SIP ORB scanner input; no historical gate row is changed.

SIP ORB has no configured scanner source. This change supplies its existing universe contract from the platform's verified stock universe and shared Schwab data, using the existing minute dispatcher. It prepares before the open and publishes a frozen ranked snapshot after the completed five-minute opening window. Missing history, provider/storage failures, pending publication and valid empty results remain distinct. Machine reads require a dedicated secret; the feature is disabled unless explicitly enabled.

## Resulting behavior

- Eligibility and RVOL follow the documented calculation contract, with exact prior-session windows and deterministic top-20 ranking. Daily eligibility is calculated once per symbol before fetching opening history.
- Preparation and publication use durable Redis progress and owner-checked leases. Lease contention is busy/skipped rather than a cron failure; storage/provider failures remain failures. Telemetry distinguishes prepared from publish_ready and includes bounded run/session context.
- The machine endpoint validates stored v1 data before returning 200, including session/window/publication timestamp, finite qualifying metrics, unique candidates and consistent exclusions/coverage. Absence returns 202; malformed data returns no-store 503 scanner_unavailable with only a bounded session/error-code log. Native freshness and the selection deadline remain separate.
- The route's 280-second execution ceiling matches the authoritative dispatcher timeout; the service's work budget and lease duration retain their separate purposes. Classification telemetry uses a deduplicated configured universe.
- The historical Superpowers plan/spec explicitly defer to canonical governance, acceptance mappings, the current runbook and changelog. They create no release authority.

## Validation

Current feature head: 118faca7429757e685824e5d06dc1da80fca8609, based on the feature history synced with main 2de673b9. Both changelog histories and the merged price-source repair are preserved.

- 74 focused scanner/route tests passed. Regression tests reproduced malformed-success and timeout inconsistencies before their correction.
- Full Node 20.19.5 suite: 9157 passed, 1 expected failure, 13 skipped and 11 todo; 942 passed files and 5 skipped. No test, timeout or required check was weakened.
- Node 20.19.5 production build and TypeScript validation passed. Scoped ESLint and full lint, cron, control-plane, size, any-count, client/server and curator gates passed.
- A separate read-only local reviewer identified an additional contradictory-empty/candidate-exclusion gap. Regression cases reproduced it; the fix enforces unique/disjoint exclusions, complete partitions and correct capped candidate counts. The reviewer independently reran all 33 HTTP contract tests and found no remaining Important issue in those files. Valid price-empty, preparation exclusions, top-20 caps and later same-session reads remain accepted.

The existing JetBrains Mono Latin subset now preloads to avoid the previously reproduced cold Next 16.3.5 internal-font-query resolver failure. Earlier before/after cold Node 20 build evidence established this workaround; family, weights, fallback and CSS variable remain unchanged. Its bounded tradeoff is an additional font preload. No dependency or TLS setting was bypassed.

These are local implementation results, not GitHub approval, production deployment, live-provider or native scheduler certification. No production credentials were used by the tests.

## Final review concerns addressed

[Review comment 6028911643](https://github.com/mark2markett/m2m-platform/pull/1260#issuecomment-6028911643): C-1 aligns maxDuration with the governed policy and pins the equality in a regression; C-2 marks both derivative historical notes and links their canonical authorities; C-3 validates unknown stored snapshots before success and records bounded failure diagnostics; N-1 corrects duplicate-symbol exclusion counts. The previous release, changelog, exclusion-code, contention, calculation, eligibility-reuse and phase-telemetry corrections remain in place. The revised head requires fresh independent GitHub review and checks.

## Independent review and release

This description is informational. Canonical authority is in CLAUDE.md, docs/implementation-plan/DECISIONS.md § D-021 and docs/delivery/ACCEPTANCE.md. D-031 permits Codex authorship with independent review and grants no deployment or trading authority. The required independent GitHub review, current-head checks and preview must pass before owner merge; scripts/delivery-gate.mjs is the canonical readiness verifier. Local author review does not clear release.

Production uses the owner-merged main commit/release artifact, with a READY production deployment tied to that commit. Secure dedicated scanner authentication, existing Schwab/Redis inputs and the enabled flag remain prerequisites. Operational proof requires a fresh authenticated snapshot at 09:35–09:39 Eastern. See docs/runbooks/CC-SIP-SCANNER.md; credential values are not part of this PR.

## Scope, limits and rollback

The implementation-plan CHANGELOG and existing R00 acceptance plan record the bounded integration. Requirement outcomes/criteria, GATES history, CURRENT-STATE completion records, DECISIONS, trading strategy, execution mode and capital are unchanged. The native shared $100,000 paper account repair is a separate Command Center change.

Live provider entitlement, shared quota, 14-session opening-history coverage, deployed Redis health and daily native scheduling still require observation. Calendar coverage is 2026–2027 and fails closed outside that range. Disable SIP_SCANNER_ENABLED to stop publication and refuse machine reads, or revert this PR to remove the logical job and endpoints. Native exit management continues when scanner input is unavailable. No orders or database migrations are introduced.
