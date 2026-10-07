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
- The historical Superpowers plan/spec explicitly defer to canonical governance, acceptance mappings, the current runbook and changelog. They create no release authority.

## Validation

Current feature head: 45d63385fb9051dca7b544f6325a9f13fbc316c5, based on the feature history synced with main 2de673b9. Both changelog histories and the merged price-source repair are preserved.

- 110 focused scanner/route/registry tests passed. New negative regressions reproduced unverified-sector admission, missing authentication checks and incomplete readiness metadata before correction; earlier snapshot/timeout regressions remain covered.
- Full Node 20.19.5 suite: 9185 passed, 1 expected failure, 13 skipped and 11 todo; 943 passed files and 5 skipped. No test, timeout or required check was weakened.
- Node 20.19.5 production build and TypeScript validation passed. Scoped ESLint and full lint, cron, control-plane, size, any-count, client/server and curator gates passed.
- A separate read-only local reviewer independently ran all 110 focused tests and found no Critical or Important issue in the revised diff. The allowlist retains all 411 currently classified stocks; shared auth checks, actual machine-route wiring, readiness limitations and supporting-change rollback were reviewed. Snapshot coverage still rejects contradictory empty results and candidate/exclusion overlap while accepting valid empty results, preparation exclusions, top-20 caps and later same-session reads.

The existing JetBrains Mono Latin subset now preloads to avoid the previously reproduced cold Next 16.3.5 internal-font-query resolver failure. Earlier before/after cold Node 20 build evidence established this workaround; family, weights, fallback and CSS variable remain unchanged. Its bounded tradeoff is an additional font preload. No dependency or TLS setting was bypassed.

These are local implementation results, not GitHub approval, production deployment, live-provider or native scheduler certification. No production credentials were used by the tests.

## Latest independent review response

[Review comment 6029579980](https://github.com/mark2markett/m2m-platform/pull/1260#issuecomment-6029579980):

- B-1 verified against canonical source: D-031 is already present in the PR's main base, not a decision introduced by this feature. See [DECISIONS.md at base 2de673b9, line 714](https://github.com/mark2markett/m2m-platform/blob/2de673b92d81109ee0b5af23f255acc1a4eec2f3/docs/implementation-plan/DECISIONS.md#L714): “D-031 — [DECIDED] Permit Codex desktop authorship with independent PR review.” The whole decision file is byte-identical to that base. No duplicate or new decision was created. Scanner release prose now cites only the existing CLAUDE rules and D-021; no feature-specific authority claim depends on an added governance record.
- C-1: an explicit allowlist admits the eleven recognized sectors and rejects Unknown/Unclassified/unrecognized strings. Positive and negative regressions preserve all 411 currently classified stocks.
- C-2: runtime metadata now declares the dedicated secret, Schwab client credentials and Supabase inputs alongside Redis/the flag. The producer shares the machine's secret validation and records failed configuration before provider/Redis work. The runbook explicitly distinguishes descriptive metadata from live readiness, explains database-first refresh-token state, and requires observed OAuth/provider/Redis publication plus native freshness proof. No mandatory bootstrap refresh-token environment key is invented.
- C-3: R00 now explicitly includes the bounded supporting font/sentinel fixes, rationale, executable acceptance coverage and rollback mapping. Disabling the scanner retains them; a full PR revert restores their previous behavior and requires fresh build/tests. The font change addresses the reproduced cold build failure; the sentinel change refuses unavailable test database requests immediately and does not permit production egress or fabricate success.
- N-1: thin tests execute the actual machine GET with real auth/store/wiring and fixture Redis responses, covering disabled/auth/config refusal, pending, ready, malformed and storage-error outcomes, current-session keys and no-store behavior.

The prior timeout, historical-note, stored-snapshot consistency, telemetry, release, calculation and lease-contender corrections remain in place. These responses are implementation evidence; the revised head still needs separate GitHub review/checks.

## Independent review and release

This description is informational. Canonical authority is in CLAUDE.md, docs/implementation-plan/DECISIONS.md § D-021 and docs/delivery/ACCEPTANCE.md. The required independent GitHub review, current-head checks and preview must pass before owner merge; scripts/delivery-gate.mjs is the canonical readiness verifier. Local author review does not clear release.

Production uses the owner-merged main commit/release artifact, with a READY production deployment tied to that commit. Secure dedicated scanner authentication, existing Schwab/Redis inputs and the enabled flag remain prerequisites. Operational proof requires a fresh authenticated snapshot at 09:35–09:39 Eastern. See docs/runbooks/CC-SIP-SCANNER.md; credential values are not part of this PR.

## Scope, limits and rollback

The implementation-plan CHANGELOG and existing R00 acceptance plan record the bounded integration. R00 explicitly maps the supporting build/test changes and rollback; canonical requirement outcomes/criteria, GATES history, CURRENT-STATE completion records, DECISIONS, trading strategy, execution mode and capital are unchanged. The native shared $100,000 paper account repair is a separate Command Center change.

Live provider entitlement, shared quota, 14-session opening-history coverage, deployed Redis health and daily native scheduling still require observation. Calendar coverage is 2026–2027 and fails closed outside that range. Disable SIP_SCANNER_ENABLED to stop publication and refuse machine reads, or revert this PR to remove the logical job and endpoints. Native exit management continues when scanner input is unavailable. No orders or database migrations are introduced.
