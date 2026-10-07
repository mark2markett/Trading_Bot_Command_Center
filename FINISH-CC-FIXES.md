# Finish the October 7 Command Center repairs

The two incident fixes have different deployment boundaries. The paper valuation import repair is a server-only native cherry-pick/restart. SIP ORB needs the platform scanner release plus its dedicated connection settings. Preserve the running paper bots, their positions, existing account/P&L and controls throughout.

## 1. Install and confirm native valuation recovery

Clone this transfer branch into a fresh temporary folder and run `APPLY-SERVER-IMPORT-FIX.ps1`. The helper validates its server-only bundle, installs the import repair, runs an isolated startup/valuation test and restarts **only CC server**. It prints actual readiness and bot heartbeats. Success requires `paper_account.ready: true`; if it fails, retain the output and diagnose the reported live quote error. Do not seed quotes or reset capital.

## 2. Update the review description and collect current review/check results

Scanner feature de30dff2 is already published. The helper below confirms publication and updates the PR description using your working native API access. From the transfer folder run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
    -File (Join-Path $fixes 'PUBLISH-PLATFORM-SCANNER.ps1') -UpdatePullRequestBody
if ($LASTEXITCODE -ne 0) { throw 'Scanner publication needs attention.' }
gh pr checks 1260 --repo mark2markett/m2m-platform --watch --interval 15
gh pr view 1260 --repo mark2markett/m2m-platform --comments
```

`$fixes` is the freshly cloned transfer directory. The publisher uses an isolated platform checkout and preserves the native Command Center branch. Publication is not a merge or deployment. Before merging, current-head independent GitHub Codex review, required quality/delivery checks and preview must pass. Inspect the current critique; canonical release authority remains CLAUDE.md and D-021. Mark performs the owner merge after reviewing those results. Never bypass a red check or publish a successful aggregate status manually.

## 3. Configure and release the platform scanner

In the **existing Vercel project serving www.mark2markets.com**, use its production environment settings:

- Create a dedicated random scanner secret of at least 32 characters and save it as `SIP_SCANNER_SECRET`. Use a password manager; keep the value out of chat, committed files and command-line arguments. It must differ from existing cron, monitor, dashboard and Schwab broker credentials.
- Verify the existing `SCHWAB_CLIENT_ID`, `SCHWAB_CLIENT_SECRET`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `UPSTASH_REDIS_REST_URL`, `UPSTASH_REDIS_REST_TOKEN`, and `CRON_SECRET` bindings are present and usable. Preserve their existing values.
- Set `SIP_SCANNER_ENABLED=true` for the operating morning, before 09:00 Eastern. The existing minute dispatcher contains the scanner's preparation/publication schedule; do not create another Windows scanner task or change physical Vercel scheduling.
- Deploy the owner-merged main release with these production settings. Confirm the production deployment is **READY**, references the actual merged main commit, and is assigned to the production domain. Environment edits require a deployment that includes them; a preview or git push is not sufficient.

The route reads stored results only; 404 means disabled/unreleased, 401 means authentication failed, and 503 means configuration/storage/snapshot is unavailable. An authenticated 202 is normal when no current-session result has been published yet. It establishes configuration/connectivity only, not provider/history readiness.

## 4. Save the matching native scanner connection securely

After production release, from `C:\Users\Administrator\trading_bots\command-center` run:

```powershell
& .\.venv\Scripts\python.exe -B (Join-Path $fixes 'CONFIGURE-SIP-SCANNER.py')
if ($LASTEXITCODE -ne 0) { throw 'Scanner connection was not configured; paste the bounded error, not the secret.' }
& .\.venv\Scripts\python.exe -B scripts\native_readiness.py --configuration-only
```

The helper prompts for the **same production scanner secret with hidden input**, then verifies an authenticated, private/no-store current-session response before changing any settings. It refuses a tracked/unignored credential file, wrong branch, disabled route, rejected secret or unavailable scanner. It refuses dotenv substitution syntax and verifies that the staged secret loads identically before replacing the file. It atomically saves only `SCANNER_URL`, `SCANNER_SECRET` and blank `SIP_SYMBOLS` in the Git-ignored `bots/sip_orb/.env.local`, preserving existing feed settings/comments. Failures before replacement leave the original file unchanged. It does not start/restart bot sessions, send orders, modify controls or initialize/reset capital. The dedicated connection applies at the next scheduled SIP session.

The helper uses the configured endpoint `https://www.mark2markets.com/api/internal/cc/sip-scanner`. Its 200/202 check proves authenticated configuration, not a fresh scan or a strategy signal. Never share its secret prompt input. Existing local profile/file access protections still apply to the credential file.

## 5. Validate Thursday, October 8, before and after the open

- Before **09:00 Eastern**: production READY with scanner inputs/enabled flag; native configuration-only checks pass; existing bot tasks are enabled for their normal starts. If task logon is interactive, remain signed in.
- Between **09:00 and 09:25**: production scanner preparation runs through the existing dispatcher. Inspect `cron_runs` and safe `[cc-sip]` logs for preparation progress and actual provider/Redis errors, not just successful task dispatch.
- At **09:35–09:39 Eastern**: run `scripts\native_readiness.py` without `--configuration-only` and review its complete output. It checks Windows session tasks, live quotes/history and the authenticated fresh scanner contract. The publication must show `publish_ready`, and native decisions must record the scanner-selected universe. A valid empty candidate list is a valid scan, not an outage.
- At **09:40** an unresolved scanner disables SIP new entries while retaining exit management. Do not restart a bot late to manufacture a missed universe. Today's October 7 selection window has already passed.

Both issues are resolved operationally only after native valuation recovery and the deployed/configured scanner's timely live publication are observed. Local tests, bundle checksums, registered tasks and configuration presence cannot substitute for those two results.
