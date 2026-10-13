# October 13 SIP publication repair

Current review: https://github.com/mark2markett/m2m-platform/pull/1296
Pinned head: `8d110664fe5f7ff15b3bb08b78446d824c98ae08`.

Today's final publication began at 09:39:43.579 ET and failed at 09:40:07.378. BBIO and DHR lacked the 09:33 opening bar. A controlled latency regression reproduces the separate-per-stock Redis cache scan crossing the deadline. Bounded MGET/EXISTS reads replace that scan; existing corrupt keys still block. The final-minute exclusion policy now runs through October 16 by owner approval, then expires. Invalid data and provider/auth/storage/quote failures continue to block; no prices or volumes are invented.

The platform PR changes no native source, capital, P&L, controls, orders or schedules. The actual installed native v1 parser accepts October 14/16 synthetic snapshots. That compatibility check is not a live scanner pass.

After current-head required checks and review pass, Mark runs `COMPLETE-SIP-PUBLICATION-REPAIR.ps1`. It verifies owner identity, pinned review head, canonical readiness, mergeability and protected owner merge, then checks the production health release SHA against the actual merge commit. It refuses changed or unreviewed heads and never bypasses checks. A rerun after merge verifies deployment only.

On the next trading morning, run `scripts/native_readiness.py` during the session. Between 09:35-09:39 ET verify a current-session authenticated scanner snapshot and successful native SIP selection/heartbeat. Use `COLLECT-CC-REVIEW.ps1` after the run to preserve private numeric cache/provider timing and per-stock exclusion evidence. Configuration-only output, preview deployment, busy/skipped cron rows and synthetic tests cannot establish live publication.

Strict completeness returns on Monday October 19. The existing check-before-result-write timing edge is retained: a write begun immediately before 09:40 can finish afterward, so timely native delivery remains a required observation. Do not restart bots to force today's missed opening entries.

## Current-head review concerns to read before owner merge

The trusted review of head8d110664 approved with no blockers and two nonblocking concerns. Owner paper-test decisions are recorded in REVIEWER-DECISIONS and mirrored in CURRENT-STATE/CHANGELOG; the reviewer prefers another anchor in the separate implementation-plan DECISIONS ledger. CLAUDE's session kickoff already names REVIEWER-DECISIONS as the authoritative owner-verdict source.

The null-slot MGET/EXISTS absence check deliberately refuses a key that appears between reads. Under the current date lease, the owner performs all opening cache writes only after the batch scan; other producer owners cannot write through the fence. External/manual cache writers can cause a conservative false storage failure, rather than silently masking a corrupt key. Atomic cache reads are a possible follow-up; this patch retains fail-closed behavior and does not add external writers.

Mark's owner merge is acknowledgement of the current-head review, including these concerns. The helper first requires canonical readiness, then prints this review notice before requesting the protected owner merge.
