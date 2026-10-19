# Schwab execution readiness — October 19, 2026

Status: NOT VERIFIED FOR SCHWAB-SIDE PAPER EXECUTION. No live trading is authorized.

The owner requires Schwab real-time equities and futures data, Polygon.io real-time
options data, and execution inside Schwab, paper first and live only after testing
and explicit owner approval. Local simulated fills do not satisfy the broker
execution part of that test.

## Code evidence

Inspected native source: c843780389c022b5f928f2754032905dcf1c2dc6.

| Requirement | Current evidence | Remaining acceptance |
| --- | --- | --- |
| Schwab equities data | `cc_sdk/cc_sdk/schwab_feed.py` calls Schwab market-data endpoints; the owner's October 19 probe retrieved three stocks' historical bars. | Fresh real-time quote timestamps and entitlements must be verified in the running session. Historical bars do not certify real-time streaming. |
| Schwab futures data | The five current bot manifests use stocks, ETFs or equity options; no futures-specific native bot path was found. | Verify the required futures symbols, entitlement, session rules and quote timestamps. Do not certify futures from an equity quote test. |
| Polygon options | `bots/gap_go_spread_bot/bot.py` uses `MixedFeed`; its underlying comes from Schwab and its chains from `polygon_options.py`. | Verify the running Polygon subscription supplies fresh, real-time quotes for the actual contracts. |
| Schwab-side paper orders | Intraday and spread runners create local `paper-...` IDs and record simulated fills; `PaperBroker` records local orders and synthetic paper stops. The shared market-data session intentionally has no order methods. | A documented, supported Schwab paper/sandbox order interface and paper account identity are prerequisites. Then verify broker acknowledgements, IDs, partial fills, rejection, cancellation, replacement and reconciliation. |
| Later live execution | The SPY daily bot has a separately guarded `SchwabBroker`; this is not an implemented, verified fleet-wide paper/live execution adapter. | Complete a broker lifecycle integration and risk/exit tests for every bot before a separate owner-authorized live release. Never substitute live orders for unavailable paper execution. |

The API-client project's README states that paper trading is not supported:
https://github.com/alexgolec/schwab-py/blob/43c4614965bdc434bd87fcd49f959db66338185e/README.rst#L103-L114
This is client-project documentation, not a verified current statement from Schwab.
The developer portal and public search were inaccessible through this environment's
network proxy; a newer or separately provisioned Schwab paper API has not been ruled out.

If Schwab has provided a supported paper/sandbox API, its product documentation and
account/environment boundary must be established before implementing its adapter.
Do not infer a paper environment from an account nickname, a local mode flag or a
locally generated order ID. Never use real-money orders as a paper connectivity test.

The scanner completeness proposal in m2m-platform PR #1322 addresses three missing
opening minutes and can publish the verified remainder after an explicit opt-in.
It does not implement Schwab-side paper orders, clear SIP's four-loss pause, prove
future market-data availability, or complete the broker execution acceptance test.

No credentials, orders, positions, capital, risk controls, execution modes or
production configuration were changed by this audit.
