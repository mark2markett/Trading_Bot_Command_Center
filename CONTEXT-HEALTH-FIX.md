# Native daily-context health repair

Review source commit8331fe68782fa55935bb18692fd6737bfa9781c3 (three allowlisted files, parentff9a16f937d960fbc41cc21ea0ee6dfadd19b104). The installer preserves feat/options-m7 and applies only this commit, not preceding bundle history. Install after16:15ET or before09:20ET, with five paper bots, no running bot commands, open positions or unresolved orders, and clean Git staging area and repair targets. Unrelated unstaged edits and untracked files are preserved. Unknown source is refused. It stages and tests the reviewed source before applying, backs up the ledger read-only and verifies installed source identity. It never restarts bots or changes schedules/controls/capital/history.

The repair keeps selected stocks visible when prior-session daily history fails, records sanitized data_errors and retries missing contexts at most once per poll, after exits. Context-less symbols cannot enter. Healthy context is reused. Valid empty scanner selection remains distinct from data failure. Unresolved errors at session completion remain failed rather than being overwritten by Bot.run's normal success heartbeat.

Validation:11 new behavioral tests observed10failures/1passing empty-universe control before implementation.66 focused tests,250 full native Python tests and11 existing dashboard tests passed.7 installer preflight tests cover read-only operation, CRLF, unknown source, open positions/orders, missing ledger, paper-only fleet and session-window refusal. Windows PowerShell installer execution remains owner-side verification.

This improves truthful health reporting and recovery; it does not manufacture missing bars or certify current provider availability. SIP latency repair105ad8a9 is deployed; authenticated publication and native consumption at the next opening are still required. Recorded SIP exclusions expire afterOctober16; strict completeness resumesOctober19.


## October 14 installer correction

The original whole-checkout check rejected normal local changes to bots/spy_mr_bot/bot.log, scripts/dev.sh and the untracked October 4 handoff. Git preflight now rejects staged changes anywhere and tracked, untracked or ignored changes at the three repair targets only. It checks twice, including after staged regression tests and immediately before applying. No stashing, reset, cleanup or unrelated commit occurs.

Real Git tests reproduce the exact reported file pattern, apply the three-file repair and verify all three owner files remain byte-identical, the branch stays feat/options-m7, the index is clean and the commit contains only the reviewed targets. An ignored repair-target file is also refused. A separate rehearsal applies the actual published8331fe6 bundle to an isolated checkout with those local changes and verifies the updated source digest and preserved file hashes. All64 transfer tests pass. Existing native source payload and all process/time/position/order/paper/checksum guards are unchanged. Windows PowerShell execution remains owner-side verification.
