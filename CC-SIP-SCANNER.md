# Command Center SIP scanner

This dedicated scanner supplies the existing paper Stocks-in-Play ORB strategy. It uses Schwab stock market data; it does not place orders or change bot stops, sizing, or portfolio capital. The existing broad platform scanner and Stock Intelligence V2 are not substitutes for this contract.

## Deployment inputs

Production deployment uses the owner-merged `main` commit/release artifact after current-head independent review and required checks pass. A feature-branch preview is not the production release; the READY production deployment must match the merged commit. Leave `SIP_SCANNER_ENABLED` unset until prerequisites and an operating morning window are available. Enable with the exact value `true` before 09:00 Eastern on a trading day.

Required existing platform inputs: working shared Schwab token state and its existing OAuth service; `CRON_SECRET`; `UPSTASH_REDIS_REST_URL` and `UPSTASH_REDIS_REST_TOKEN`. Redis is required, with no in-memory substitute. Configure a new `SIP_SCANNER_SECRET` of at least 32 random characters. It must differ from `CRON_SECRET`, `MONITOR_SECRET`, `DASHBOARD_PASSWORD`, and `SCHWAB_BROKER_SECRET`. Enter credentials securely in deployment settings, never in URLs or committed files. No database migration is required.

Native bot inputs in `bots/sip_orb/.env.local`: `SCANNER_URL=https://www.mark2markets.com/api/internal/cc/sip-scanner`, `SCANNER_SECRET` matching the new dedicated platform secret, and the existing shared Schwab token-broker configuration. Keep `SIP_SYMBOLS` blank for scanner-only operation. Populating it explicitly opts into a fixed operator watchlist fallback; it is logged as such and is not a relative-volume scan. A valid empty scanner result never triggers that fallback.

## Daily operation and evidence

One new logical job is dispatched by the existing minute control plane. It prepares at 09:00, 09:05, 09:10, 09:15, 09:20, 09:25 Eastern, and retries publication each minute from 09:35 through 09:39. Paired UTC expressions plus an Eastern guard handle daylight saving time. The shared exchange calendar currently enumerates 2026 and 2027 full closures; update it before later years. Early-close days still have a normal opening window. Physical `vercel.json` scheduling is unchanged.

The stock universe is the actual configured `ALL_SYMBOLS` list filtered by verified sector classification; ETFs/funds and unknown classifications are excluded. Logs record the classification exclusion count. Price must exceed $5, completed 20-session average share volume must be at least 1 million, and Wilder ATR(14) must exceed $0.50. RVOL is the sum of exactly five completed 09:30–09:34 minute volumes divided by the mean of the same window over exactly 14 previous exchange sessions. Missing historical windows exclude that symbol with a reason. Today’s incomplete window or a provider/auth/storage failure prevents publication and is retried. No missing volume is invented.

Preparation is cached per symbol and resumes after failures. Current completed opening volumes are also cached for retry; quotes are obtained afresh before publication and must be current. Four workers share pacing of at most about 100 data requests/minute within this scanner; other platform/fleet requests share the provider’s overall limit, so 429 remains a retryable outage. Work has a 240-second budget and a 330-second ownership lease. Redis writes atomically verify the lease owner. A session snapshot is immutable, retained seven days with its coverage and exclusions. A ready result can legitimately contain zero candidates.

`cron_runs` and safe `[cc-sip]` logs record preparation/publication status and failure codes. Redis keys use `cc:sip:v1:YYYY-MM-DD:*`; inspect `preparation` for exclusions/failures and `result` for the frozen published snapshot. Native decisions record `SCANNER`, `SCANNER_PENDING`, `SCANNER_ERROR`, `SCANNER_FALLBACK`, or `SCANNER_UNAVAILABLE`; per-bot JSONL records heartbeat health. The native client validates version, date, exact window, coverage, finite rows, duplicate symbols, and a maximum 300-second age. It does not follow redirects.

The authenticated machine GET only reads stored results: disabled 404, unauthorized 401, not-ready 202, storage/configuration error 503, ready 200. Every response is private/no-store. At 09:40 Eastern, an unresolved bot disables new entries, retains degraded heartbeat evidence, and keeps managing exits. Restarting after 09:40 does not fabricate a new universe.

## Release checks

Cloud fixtures demonstrate calculation, auth, retry/isolation, and the real SIP rules→risk→paper fills→EOD exit. They do not establish live provider history coverage, entitlement, quote freshness, or Windows scheduler readiness. Before enabling for a morning, verify deployment status, Redis health, shared Schwab connection, and preparation completeness. At 09:35 verify the authenticated v1 snapshot and native `UNIVERSE` decision. Review exclusions rather than assuming all configured stocks qualify.

The operator chose one shared $100,000 paper account. APPLY-RUNTIME-FIXES.ps1 installs that separate account repair; the scanner itself does not seed capital. Native readiness still requires current marks for open positions. Paper execution only; operator promotion remains separate.

The scanner calendar fails closed outside its covered 2026–2027 years, including lookback windows that cross into an uncovered year. This avoids pretending an unlisted holiday is a trading session; extend the shared calendar and scanner guard together before using such a window.
