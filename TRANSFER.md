# SIP scanner delivery — 2026-10-06

Command Center source is published on `feat/sip-scanner`, commit `9d2cbc2ed327b76c00dd7007dbc402ac7ba42380`, based on cloud pre-open repair `2f7bef3`. The native `26ea7cb` repair is patch-equivalent. Main was not changed.

Platform scanner is prepared at `f6b9413d31102b5758016025d55326089fb3d32a` on `feat/cc-sip-scanner`, base `1e32fd94646526818593713ca3c53ad52493975d`. This cloud task can read m2m-platform but its push failed with a GitHub authentication error. The incremental platform bundle and readable patch preserve all three commits for import using an authorized platform checkout. No main merge or production deployment was performed.

## Retrieve the package on Windows

```powershell
$transfer = Join-Path $env:TEMP ('cc-sip-' + [guid]::NewGuid().ToString('N'))
git clone --depth 1 --single-branch --branch transfer/sip-scanner https://github.com/mark2markett/Trading_Bot_Command_Center.git $transfer
if ($LASTEXITCODE -ne 0) { throw 'GitHub retrieval failed.' }
Get-Content (Join-Path $transfer 'TRANSFER.md')
```

After bot sessions finish, install only the native scanner client:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $transfer 'APPLY-SIP-SCANNER.ps1')
```

The helper validates `feat/options-m7` and the prior repair, backs up the ledger read-only, imports the new branch, applies the single scanner commit idempotently, and runs native regressions. It leaves the server and existing task schedules running and preserves unrelated changes. No sessions are started and no credentials/capital are changed. PowerShell itself still requires native validation; the patch was independently backported against the original native base plus the two production repairs in cloud, preserving the branch, log/dev changes and untracked handoff.

Publish the prepared platform review branch using your native GitHub access:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $transfer 'PUBLISH-PLATFORM-SCANNER.ps1')
```

The publisher creates an isolated temporary platform checkout, validates the origin, imports the bundle, and pushes only `feat/cc-sip-scanner`. It does not merge main or change the production deployment. If you already have a local m2m-platform checkout, an optional `-Repo` parameter uses it and preserves its checked-out branch.

Review/deploy the platform branch through the normal pipeline, set the dedicated secret securely on both sides, and enable the scanner before 09:00 Eastern on a trading day. See `CC-SIP-SCANNER.md` for the exact schedule, v1 contract, defaults, safe failure behavior and logs. Keep SIP_SYMBOLS blank for scanner-only mode. A fixed list is an explicit operator fallback, not a scanner.

## Verification and outstanding checks

- 30 platform scanner tests pass, production typecheck/lint/cron registry/size/any/client-server gates pass.
- 201 Command Center Python tests pass.
- Actual platform-produced fixture passes real SIP rules → risk → paper entry/fills → EOD exits.
- Browser harness: 34 PASS / 0 FAIL / 7 NOT COVERED, isolated runtime and source cleaned.
- Independent review: both Important findings fixed with RED/GREEN regressions, minor coverage/calendar findings fixed; follow-up found no remaining Critical/Important issues.
- Broad platform suite: 9035 pass, 10 fail, 1 expected fail, 13 skipped, 11 todo. The six failing existing files also fail on unchanged main in this environment; timeout test identities vary across runs. These are not represented as a green release gate.
- Next production build fails on existing Google Fonts egress 403 (four fonts). Required domains: fonts.googleapis.com and fonts.gstatic.com. No font bypass or product font changes were made.
- Live Schwab completeness/entitlement/freshness, deployed Redis and machine auth, and native Windows scheduling remain unverified without deployment credentials/native results.
- Portfolio capital basis remains unanswered; no equity is seeded and full portfolio risk readiness is not claimed.

Bundles contain source only; no live databases, logs, backups, credential files or review ZIPs are published. SHA256.txt covers the transfer payload.
