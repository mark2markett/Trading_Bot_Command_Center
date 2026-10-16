# Paused SIP scanner and attention display repair — October 16

Two defects were reproduced and repaired. A session with entry pauses returned before requesting its opening universe,
then incorrectly reported scanner unavailability at 09:40. The repair lets existing read-only scanner observations run
while entries remain paused. Genuine scanner delays still fail at the same hard deadline; stops/exits remain first.
No pause is cleared, no late selection is accepted and no trading or risk rule changes.

The server's single-page fallback also returned dashboard HTML with HTTP 200 for nonexistent API paths. It now returns
JSON 404 for those paths while preserving browser routes. A legacy server with no incident endpoint cannot provide
automatic incident handling simply by refreshing its page; the full runtime release must be installed separately.

## Immediate display correction while a position is open

This is a separate, reversible static-asset update. It makes the already-tested attention panel show an unavailable
monitor instead of claiming zero open issues when the incident endpoint is absent. It does not install the worker,
enable recovery, change source code, restart the server/bots, query trade providers, write the financial database or
clear controls. It checks the running server's repository identity and archive checksum, keeps old assets for open
tabs, backs up the index, replaces it atomically and verifies served bytes. Failed verification restores the old index.

```powershell
& {
    $ErrorActionPreference = 'Stop'
    $repair = Join-Path $env:TEMP ('cc-attention-display-' + [guid]::NewGuid().ToString('N'))
    git clone --depth 1 --single-branch --branch transfer/sip-scanner `
        https://github.com/mark2markett/Trading_Bot_Command_Center.git $repair
    if ($LASTEXITCODE -ne 0) { throw 'Download failed.' }
    powershell.exe -NoProfile -ExecutionPolicy Bypass `
        -File (Join-Path $repair 'APPLY-ATTENTION-DISPLAY.ps1')
    if ($LASTEXITCODE -ne 0) { throw 'Display update needs attention; paste the output.' }
}
```

Press **Ctrl+F5** afterward. The expected legacy-server result is **Monitor unavailable / Automatic recovery not enabled**.
That is an honest report of missing runtime functionality, not a claim that monitoring or SIP has recovered.
The command prints an index backup receipt. Old assets are retained; no financial rollback is ever performed.

## Runtime repair for subsequent sessions

The checksummed `attention-native.bundle` includes the two fixes and all preceding reliability/expiration changes.
Use INSTALL-ATTENTION-HANDLING.ps1 under its existing maintenance guards only when flat, orders resolved and bot commands
idle. It recognizes all three preceding complete releases. Existing positions must not be closed just to install.
See ATTENTION-RELEASE.md and EXPIRATION-CONTEXT-RELEASE.md for the guarded command and recovery receipt procedure.

Verify the actual pause reasons before considering any audited rearm. A risk pause, four-loss guard, failed scanner and
old dashboard are separate facts. A currently healthier equity display does not authorize resetting a latched pause.
The original 09:40 scanner deadline and expiry of the paper incomplete-bar exception on October 16 are unchanged.
Strict bar completeness resumes October 19. Today's failed opening must remain in the record; restarting after the
deadline does not turn it into a valid opening test. Verify publication/native selection in the next eligible session.
