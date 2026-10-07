## Outcome and acceptance

Delivery requirements: R00
Acceptance plan: docs/delivery/plans/R00-cc-sip-scanner.json
Closes gate: NONE — bounded restoration of the existing Command Center paper SIP ORB scanner input; no historical gate row is changed.

SIP ORB has no configured scanner source. This change supplies its existing universe contract from the platform's verified stock universe and shared Schwab data, using the existing minute dispatcher. It prepares before the open and publishes a frozen ranked snapshot after the completed five-minute opening window. Missing history, provider/storage failures, pending publication and valid empty results remain distinct. Machine reads require a dedicated secret; the feature is disabled unless explicitly enabled.

## Resulting behavior

- Eligibility uses the eleven recognized FMP/Yahoo stock sectors and refuses unknown/unclassified labels; RVOL follows the documented calculation contract, with exact prior-session windows and deterministic top-20 ranking. Daily eligibility is calculated once per symbol before fetching opening history.
- Preparation and publication use durable Redis progress and owner-checked leases. The enabled producer refuses missing, short or shared scanner secrets before provider/Redis work, using the same configuration check as the machine endpoint. Lease contention is busy/skipped rather than a cron failure; storage/provider failures remain failures. Telemetry distinguishes prepared from publish_ready and includes bounded run/session context.
- The machine endpoint validates stored v1 data before returning 200, including session/window/publication timestamp, finite qualifying metrics, unique candidates and consistent exclusions/coverage. Absence returns 202; malformed data returns no-store 503 scanner_unavailable with only a bounded session/error-code log. Native freshness and the selection deadline remain separate.
- The route's 280-second execution ceiling matches the authoritative dispatcher timeout; the service's work budget and lease duration retain their separate purposes. Classification telemetry uses a deduplicated configured universe.
- Telemetry bootstrap/completion exceptions produce explicit no-store scanner 503 responses; nested failure logging preserves the primary error and null-ID terminal fallbacks retain scanner attribution.
- Cached cron publication uses the same stored-snapshot validator as the machine read. Invalid immutable results fail with SIP_SNAPSHOT_INVALID, produce no publish_ready telemetry and trigger neither overwrite nor replacement data requests.
- The original plan/spec are archival narrative with status metadata and canonical links, without build tasks or release instructions. The same-PR changelog entries are consolidated.

## Validation

Current feature head: ab35e97387708597893353c986993b0b8580cac4, based on the feature history synced with main 436b8b4e. Main's daytime-read job and changelog are preserved; the merged price-source repair remains intact.

- 120 focused scanner/route/registry tests passed. New cached-publication regressions reproduced malformed version/session/coverage admission and cron false-ready telemetry before correction; valid cached empty results remain supported. Earlier telemetry, auth, snapshot and timeout regressions remain covered.
- Full Node 20.19.5 suite: 9216 passed, 1 expected failure, 13 skipped and 11 todo; 946 passed files and 5 skipped. No test, timeout or required check was weakened.
- Node 20.19.5 production build and TypeScript validation passed. Scoped ESLint and full lint, cron, control-plane, size, any-count, client/server and curator gates passed.
- A separate read-only local reviewer independently ran all 30 service/cron-route tests for this revision and found no Critical or Important issue. Main's full registry entries and changelog body were verified preserved; only the SIP additions and governed counts differ (93 jobs, 101 schedules). Earlier independent review covered the machine endpoint and other scanner tests. The allowlist retains all 411 currently classified stocks; shared auth checks, actual machine-route wiring, readiness limitations and supporting-change rollback were reviewed. Snapshot coverage still rejects contradictory empty results and candidate/exclusion overlap while accepting valid empty results, preparation exclusions, top-20 caps and later same-session reads.

The existing JetBrains Mono Latin subset now preloads to avoid the previously reproduced cold Next 16.3.5 internal-font-query resolver failure. Earlier before/after cold Node 20 build evidence established this workaround; family, weights, fallback and CSS variable remain unchanged. Its bounded tradeoff is an additional font preload. No dependency or TLS setting was bypassed.

These are local implementation results, not GitHub approval, production deployment, live-provider or native scheduler certification. No production credentials were used by the tests.

## Latest independent review response

[Review comment 6038590145](https://github.com/mark2markett/m2m-platform/pull/1260#issuecomment-6038590145) reported APPROVE_WITH_CONCERNS and no blockers on the previous head:

- C-1: cached cron publication now calls the same validSnapshot validator as machine reads before reuse. Invalid stored version/session/coverage fails with bounded SIP_SNAPSHOT_INVALID and no-store HTTP 503 at the actual cron route, never publish_ready. Existing data remains immutable for diagnosis; no replacement provider work occurs. Negative service regressions and a real-route regression cover this path; valid empty reuse and ordinary idempotence remain covered.
- C-2: historical plan/spec files now contain archival status metadata and pure narrative with canonical links. Imperative build/commit/release tasks and stale operational prerequisites were removed.
- N-1: the two adjacent same-PR CHANGELOG records are consolidated into one durable October 6–7 entry, preserving the other main history.

The revision also integrates current main 436b8b4e with its daytime-read job intact. Governance, physical scheduling, workflow permissions, required checks, trading strategy and native account capital are unchanged. Local validation does not resolve a remote status-publisher failure or clear GitHub release checks; a new independent review/check run is required for this head.

## Independent review and release

This description is informational. Canonical authority is in CLAUDE.md, docs/implementation-plan/DECISIONS.md § D-021 and docs/delivery/ACCEPTANCE.md. The required independent GitHub review, current-head checks and preview must pass before owner merge; scripts/delivery-gate.mjs is the canonical readiness verifier. Local author review does not clear release.

Production uses the owner-merged main commit/release artifact, with a READY production deployment tied to that commit. Secure dedicated scanner authentication, existing Schwab/Redis inputs and the enabled flag remain prerequisites. Operational proof requires a fresh authenticated snapshot at 09:35–09:39 Eastern. See docs/runbooks/CC-SIP-SCANNER.md; credential values are not part of this PR.

## Scope, limits and rollback

The implementation-plan CHANGELOG and existing R00 acceptance plan record the bounded integration. R00 explicitly maps the supporting build/test changes and rollback; canonical requirement outcomes/criteria, GATES history, CURRENT-STATE completion records, DECISIONS, trading strategy, execution mode and capital are unchanged. The native shared $100,000 paper account repair is a separate Command Center change.

Live provider entitlement, shared quota, 14-session opening-history coverage, deployed Redis health and daily native scheduling still require observation. Calendar coverage is 2026–2027 and fails closed outside that range. Disable SIP_SCANNER_ENABLED to stop publication and refuse machine reads, or revert this PR to remove the logical job and endpoints. Native exit management continues when scanner input is unavailable. No orders or database migrations are introduced.
