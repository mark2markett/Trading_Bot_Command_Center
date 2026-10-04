# M7 — Options paper trading: design (for owner approval)

Status: DRAFT, 2026-10-04. Nothing built. Paper only. Schwab remains the only broker and the only market data in the
order path (hard rule 1). Risk checks stay in `cc_sdk`, in the bot process, fail closed (hard rule 2). No existing
risk check is loosened; equity behaviour is unchanged and every existing test must stay green.

## 1. Goal

Run **one** options strategy in paper — a defined-risk **debit vertical driven by the existing gap_go signal** — on
infrastructure that later strategies can reuse, and report it honestly enough to tell an options edge from leverage.

Out of scope for M7: 0DTE condor and straddle (no validated signal behind them; M2M's own capped-straddle study,
RES-222, found it break-even at best), the daily-MR vertical (next, same plumbing), live orders, early exercise.

## 2. What already exists (verified 2026-10-04)

- Schwab chains are not yet called. The fleet's Schwab session (`schwab_feed.py`) makes three read-only market-data
  calls and has no trading methods; a test pins that.
- Risk engine `cc_sdk/risk.py`: notional = `qty × ref_price` (no contract multiplier). Kill/pause bypass exists for
  risk-reducing orders, and `CLAUDE.md` already defines "closing an options spread" as risk-reducing.
- Ledger: `positions` keyed by (bot_id, symbol); an OCC option symbol fits that key.
- **Historical data for a backtest exists.** M2M's ORATS archive in R2 (`m2m-orats-archive`, read-only use):
  continuous daily strike files 2016-01-04 → 2026-06-18 (250–254 files per year). SPY, QQQ and IWM are present with
  full chains including 0–1 DTE, bid/ask, IV and greeks (checked on 2018-07-03, 2021-07-06, 2026-06-18). Pre-2021
  files use a different column order; read by header name, never by position. ORATS lapsed 2026-06-18; 2026-06-22 →
  07-01 is a permanent gap.

## 3. Milestones (each: tests first, verify output pasted, commit `M7.n: …`)

**M7.1 Chains.** `SchwabFeed.chain(symbol, from_date, to_date)` → `/marketdata/v1/chains`, a fourth read-only call.
Returns `OptionQuote(occ, underlying, expiry, strike, right, bid, ask, mark, delta, theta, iv, oi, volume, quote_time)`.
The no-trading-surface test is extended to allow exactly this one addition.

**M7.2 Risk engine (tests first — the part that loses money if wrong).**
- `Order` gains `multiplier: int = 1`; notional = `qty × ref_price × multiplier`. Equity orders keep multiplier 1, so
  every existing check computes exactly what it does today.
- New per-bot limit `max_premium_usd` (default $5,000): the most a single options entry may pay in total debit.
- A spread is approved only if **every leg** passes; one leg failing rejects the whole spread.
- Closing a spread is risk-reducing: it bypasses pause and kill, as already defined.
- New tests: multiplier applied; premium cap rejects; one bad leg rejects all; closing passes under KILL;
  all existing `test_risk.py` cases unchanged.

**M7.3 Paper fills and positions.** `cc_sdk/options.py`:
- Fill each leg at mid ± 25% of its bid-ask spread, always against us. Multi-leg orders fill all-or-none.
- Refuse to fill a leg with zero bid, crossed quotes, a spread wider than 15% of mid, or a quote older than the
  bot's `stale_quote_s`. A refused leg refuses the spread.
- Positions stored per leg (OCC symbol, signed contracts, price per share); P&L applies the ×100 multiplier.

**M7.4 Honest reporting (the M2M lesson).** Per trade, record the underlying move, the spread P&L, and the P&L of
**shares holding the same delta at entry**. The bot's verdict line and the research table report: profit factor on
up-days vs down-days of the underlying, and spread P&L minus share-equivalent P&L. If the spread does not beat the
share-equivalent position, it is gap_go with leverage, and the report says so in those words. Bot card gains delta,
theta and days to expiry.

**M7.5 The bot: `bots/gap_go_spread_bot/`.** Reuses `GapGoRules` unchanged (gap ≥ 70 bp, 30-min range break).
- Long gap → call debit spread; short gap → put debit spread.
- Expiry: nearest with **2–7 days** left (avoids same-day pin risk). Long leg nearest the money; short leg one ATR
  further in the signal direction, rounded to a listed strike.
- Size: `floor(risk_usd / (net_debit × 100))`, within `max_premium_usd`.
- Exit: close the spread at the gap_go stop, or at 15:55 ET, the same day — the same exits gap_go uses.
- These are starting values, labelled as such in the manifest; changing them is a research decision, not a tweak.

**M7.6 Backtest (research harness only, never in the order path).** Prices from the ORATS archive, downloaded only
for gap days (≈30 per symbol per year).
- Exits at the close use the archive's end-of-day bid/ask: measured prices.
- **Entries happen intraday, and the archive has one snapshot per day.** Entry legs are priced with Black-Scholes at
  the intraday underlying price using the **prior day's** IV for that strike and expiry — no look-ahead. These
  entry prices are modelled, and every report labels them so.
- Intraday underlying prices: the existing 1-minute proxies end 2020-05, which gives about 4.4 years of overlap with
  the archive (≈130 gap_go trades per symbol, below the 200-trade bar).
- Pass bar = the existing research bar **plus** beating the share-equivalent position in at least 4 of 5 folds.

## 4. Decisions needed from Mark

1. **Approve M7.1–M7.5** (forward paper). Estimate 2–3 days.
2. **Backtest entry pricing:** accept modelled entries from prior-day IV (recommended), or skip the backtest and rely
   on forward paper only.
3. **Backtest window:** stay with 2016-01 → 2020-05 on existing minute data (recommended first pass), or add
   SPY/QQQ/IWM minute history for 2020-05 → 2026-06 from another source. That data would live only in `research/`,
   never in the order path, but it is a second vendor in this repo and so needs your say-so.
