# Apply the consolidated runtime repair

This package updates the native feat/options-m7 checkout, skipping patches already present. It includes the SQLite/threading and Windows harness-launch repairs, authenticated SIP client, interruption diagnostics, shared paper account, history cooldowns, and native readiness gate. Main is not used or changed.

Run after bot commands have finished. The installer refuses active bot commands, backs up the ledger, stops only the CC server scheduled task, applies missing commits, runs native Python tests with a disposable CC_VAR, installs the checksum-verified production dashboard build, initializes the operator-approved shared $100,000 paper account once, and restarts the server. It preserves the existing daily-bot log, dev.sh, handoff files and branch. It neither starts sessions nor clears controls nor changes task settings. Tests/source were verified in cloud; the PowerShell installer itself still requires native execution.

```powershell
& {
    Set-Location C:\Users\Administrator\trading_bots\command-center
    $update = Join-Path $env:TEMP ('cc-runtime-' + [guid]::NewGuid().ToString('N'))
    git clone --depth 1 --single-branch --branch transfer/sip-scanner https://github.com/mark2markett/Trading_Bot_Command_Center.git $update
    if ($LASTEXITCODE -ne 0) { throw 'Download failed.' }
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $update 'APPLY-RUNTIME-FIXES.ps1')
    Write-Host "Update folder: $update"
}
```

A failed scanner prerequisite after the final SOURCE UPDATE INSTALLED message means the code/account update succeeded but deployment remains not ready. Do not repeat older separate installers. Paste the command output; it contains no credential values. For a cherry-pick or native-test failure, preserve state and paste output before starting bot sessions.

## Scanner remains a deployment step

Platform producer branch **feat/cc-sip-scanner**, **e8146e8**, was published successfully. Review/merge and deploy through the normal platform process:
https://github.com/mark2markett/m2m-platform/compare/main...feat/cc-sip-scanner

Existing platform requirements: working shared Schwab state, CRON_SECRET, UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN. Add a new dedicated SIP_SCANNER_SECRET (at least 32 random characters, distinct from other admin/broker secrets) through secure deployment settings. Set SIP_SCANNER_ENABLED=true before 09:00 Eastern on the intended trading day. Never paste a secret into this chat or put it in a URL.

On Windows, edit the existing bots/sip_orb/.env.local in your local editor, preserving its existing values. Add SCANNER_URL=https://www.mark2markets.com/api/internal/cc/sip-scanner and SCANNER_SECRET equal to the dedicated platform secret. Keep SIP_SYMBOLS blank for scanner-only operation. Existing shared Schwab credentials are reused. The branch push, enabled flag, and local URL alone do not prove that daily preparation/publication worked.

Before the next session, use `.venv\Scripts\python.exe scripts\native_readiness.py --configuration-only`. At **09:35–09:39 Eastern**, run without that flag for actual Windows scheduler state, provider quote/minute-history freshness and the authenticated current-day snapshot. Ordinary Windows `scripts\closed_loop.py` runs now require native configuration by default. `--sandbox-only` explicitly opts into offline code checks. `scripts\closed_loop.py --require-ready` additionally requires the live morning gate. A 202/pending, disabled 404, auth error, stale data, missing account or failed API is a failure, never a pass or an assumed no-trade day.

Interactive Windows tasks require the user to stay signed in. Signing out/forced process termination can still end them; the earlier termination cause was not established. No scheduler security settings or service-account credentials are guessed by this update.

## Validation

235 Python tests pass, 11 dashboard tests pass, production dashboard build passes. Closed loop: 34 PASS, 0 FAIL, 7 NOT COVERED (live native/provider integrations explicitly excluded). Independent review verified the accounting/quote/rejection fixes. None of these statements certifies Windows execution or deployed scanner readiness; those are the native gates above.
