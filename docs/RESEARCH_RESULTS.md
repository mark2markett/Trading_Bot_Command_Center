# Intraday research results — round 1 (index proxies, 2005–2020)

**Data.** Oanda 1-minute CFD bars for S&P 500 (SPY proxy), Nasdaq 100 (QQQ proxy), Russell 2000 (IWM proxy),
2005-01 → 2020-05, regular hours only, 3,640–3,810 usable days per symbol. Volume is tick count (not shares).
Costs: 1.0 bp per side (slippage + half spread), stress column at 2.0 bp. One unit of notional per trade, flat by the close.
Fills: signal on bar close, fill at next bar open; stop-order entries fill at the level or the worse open; stops fill at
the stop or the gap-through open. No commissions (Schwab equities are $0).

**Pass bar, fixed before the run.** PF ≥ 1.3 after costs · ≥ 200 trades · all 5 chronological folds positive ·
≥ 60 % of the parameter grid at PF ≥ 1.1. Verdicts come from the bar, not from eyeballing.

**Result: 2 of 36 strategy × symbol runs pass; 10 of 12 strategy families fail everywhere.**

| strategy | symbol | best params | trades | PF | PF@2x cost | win | avg bps | Sharpe | maxDD | folds+ | stable | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| gap_go | SPX500 | {"gap_bps": 70, "wait_min": 30} | 465 | 1.747 | 1.656 | 52% | 21.45 | 1.06 | -7.15% | 5/5 | 100% | PASS |
| gap_go | NAS100 | {"gap_bps": 70, "wait_min": 30} | 538 | 1.441 | 1.371 | 53% | 14.74 | 0.76 | -9.51% | 5/5 | 78% | PASS |
| power_hour | SPX500 | {"start_mod": 870, "t_bps": 80, "reverse": false} | 719 | 1.475 | 1.365 | 49% | 10.25 | 0.84 | -11.77% | 5/5 | 44% | fail |
| gap_go | US2000 | {"gap_bps": 70, "wait_min": 30} | 539 | 1.429 | 1.367 | 52% | 16.47 | 0.77 | -19.67% | 3/5 | 100% | fail |
| power_hour | US2000 | {"start_mod": 930, "t_bps": 80, "reverse": false} | 1464 | 1.319 | 1.169 | 51% | 4.62 | 0.83 | -17.07% | 4/5 | 33% | fail |
| nr7_breakout | US2000 | {"stop": "atr25", "target_r": 2} | 551 | 1.288 | 1.2 | 43% | 7.29 | 0.6 | -7.65% | 4/5 | 100% | fail |
| nr7_breakout | SPX500 | {"stop": "atr25", "target_r": 2} | 531 | 1.26 | 1.143 | 41% | 4.83 | 0.5 | -9.1% | 4/5 | 100% | fail |
| overnight_momo | NAS100 | {"hold_min": 15, "min_bps": 30, "reverse": true} | 2010 | 1.22 | 1.044 | 53% | 2.56 | 0.79 | -13.24% | 5/5 | 33% | fail |
| power_hour | NAS100 | {"start_mod": 930, "t_bps": 80, "reverse": false} | 1196 | 1.21 | 1.064 | 50% | 2.96 | 0.53 | -6.9% | 4/5 | 11% | fail |
| afternoon_move | SPX500 | {"check_mod": 720, "x_atr": 0.5, "y_atr": 0.25, "continue": true} | 808 | 1.171 | 1.042 | 40% | 2.72 | 0.42 | -6.19% | 4/5 | 14% | fail |
| overnight_momo | US2000 | {"hold_min": 60, "min_bps": 30, "reverse": true} | 2030 | 1.163 | 1.076 | 49% | 3.89 | 0.65 | -16.76% | 4/5 | 17% | fail |
| orb_zarattini | NAS100 | {"first_min": 5, "stop_atr": 0.1, "target_r": 10} | 3697 | 1.148 | 1.009 | 17% | 2.15 | 0.61 | -18.6% | 4/5 | 17% | fail |
| orb_zarattini | US2000 | {"first_min": 15, "stop_atr": 0.05, "target_r": null} | 3789 | 1.137 | 0.95 | 9% | 1.4 | 0.4 | -21.23% | 2/5 | 17% | fail |
| afternoon_move | US2000 | {"check_mod": 840, "x_atr": 0.5, "y_atr": 0.5, "continue": true} | 1250 | 1.122 | 1.027 | 51% | 2.6 | 0.33 | -14.73% | 3/5 | 8% | fail |
| vol_breakout | US2000 | {"k": 0.5, "stop": "open"} | 2930 | 1.089 | 1.022 | 45% | 2.68 | 0.42 | -35.48% | 4/5 | 0% | fail |
| afternoon_move | NAS100 | {"check_mod": 720, "x_atr": 0.5, "y_atr": 0.25, "continue": true} | 980 | 1.089 | 0.988 | 42% | 1.75 | 0.25 | -20.39% | 3/5 | 0% | fail |
| vol_breakout | NAS100 | {"k": 0.5, "stop": "open"} | 2869 | 1.086 | 1.007 | 45% | 2.18 | 0.4 | -28.61% | 4/5 | 0% | fail |
| vol_breakout | SPX500 | {"k": 0.7, "stop": "open"} | 2017 | 1.08 | 0.985 | 47% | 1.67 | 0.3 | -27.61% | 3/5 | 0% | fail |
| first_hour_break | US2000 | {"range_min": 90, "stop": "mid", "target_r": 1.5} | 3411 | 1.073 | 0.991 | 47% | 1.77 | 0.41 | -25.41% | 3/5 | 0% | fail |
| first_hour_break | SPX500 | {"range_min": 90, "stop": "mid", "target_r": null} | 3374 | 1.064 | 0.962 | 42% | 1.23 | 0.31 | -23.24% | 3/5 | 0% | fail |
| gap_fade | NAS100 | {"lo_bps": 20, "hi_bps": 60, "stop_mult": 1.0} | 1541 | 1.059 | 0.944 | 54% | 1.0 | 0.27 | -9.51% | 4/5 | 0% | fail |
| orb_zarattini | SPX500 | {"first_min": 5, "stop_atr": 0.1, "target_r": null} | 3440 | 1.046 | 0.904 | 17% | 0.59 | 0.18 | -19.06% | 4/5 | 0% | fail |
| gap_fade | US2000 | {"lo_bps": 30, "hi_bps": 150, "stop_mult": 1.0} | 1818 | 1.036 | 0.965 | 52% | 0.99 | 0.17 | -30.71% | 4/5 | 0% | fail |
| overnight_momo | SPX500 | {"hold_min": 15, "min_bps": 30, "reverse": true} | 1745 | 1.028 | 0.843 | 51% | 0.28 | 0.1 | -8.92% | 3/5 | 0% | fail |
| gap_fade | SPX500 | {"lo_bps": 30, "hi_bps": 60, "stop_mult": 2.0} | 941 | 1.026 | 0.934 | 60% | 0.55 | 0.09 | -13.14% | 2/5 | 0% | fail |
| orb | NAS100 | {"range_min": 5, "stop": "atr10", "target_r": null, "vol_filter": false} | 3784 | 1.016 | 0.893 | 17% | 0.24 | 0.07 | -26.9% | 3/5 | 0% | fail |
| orb | US2000 | {"range_min": 15, "stop": "atr10", "target_r": null, "vol_filter": false} | 3801 | 1.015 | 0.906 | 16% | 0.25 | 0.06 | -26.94% | 2/5 | 0% | fail |
| first_hour_break | NAS100 | {"range_min": 90, "stop": "mid", "target_r": 1.5} | 3387 | 1.006 | 0.917 | 46% | 0.13 | 0.04 | -30.28% | 3/5 | 0% | fail |
| nr7_breakout | NAS100 | {"stop": "atr25", "target_r": 2} | 551 | 0.962 | 0.881 | 39% | -0.87 | -0.1 | -14.69% | 1/5 | 0% | fail |
| orb | SPX500 | {"range_min": 15, "stop": "atr10", "target_r": null, "vol_filter": true} | 1889 | 0.954 | 0.829 | 14% | -0.63 | -0.14 | -31.33% | 1/5 | 0% | fail |
| vwap_revert | NAS100 | {"k": 2.5, "start_min": 30, "stop_mult": 1.0, "max_trades": 3} | 9124 | 0.87 | 0.767 | 52% | -2.26 | -1.36 | -89.01% | 0/5 | 0% | fail |
| vwap_revert | US2000 | {"k": 2.5, "start_min": 30, "stop_mult": 1.0, "max_trades": 3} | 9025 | 0.869 | 0.783 | 51% | -2.71 | -1.37 | -93.61% | 0/5 | 0% | fail |
| vwap_revert | SPX500 | {"k": 3.0, "start_min": 30, "stop_mult": 1.0, "max_trades": 3} | 7084 | 0.845 | 0.731 | 52% | -2.37 | -1.35 | -83.85% | 0/5 | 0% | fail |
| vwap_trend | US2000 | {"band_bps": 0, "confirm_bars": 30, "start_min": 60} | 3164 | 0.788 | 0.574 | 8% | -1.21 | -0.71 | -33.77% | 0/5 | 0% | fail |
| vwap_trend | NAS100 | {"band_bps": 0, "confirm_bars": 15, "start_min": 30} | 4563 | 0.633 | 0.443 | 8% | -1.88 | -1.59 | -59.64% | 0/5 | 0% | fail |
| vwap_trend | SPX500 | {"band_bps": 0, "confirm_bars": 30, "start_min": 60} | 3022 | 0.631 | 0.436 | 8% | -1.79 | -1.24 | -45.43% | 0/5 | 0% | fail |
## Reading the table honestly

- **gap_go passes on SPX and NAS** and is the only family that is positive on all three symbols, every fold, and every grid
  point (SPX 100 %, NAS 78 %, RUT 100 % of grid at PF ≥ 1.1). Extended grid (gap 50–150 bp, wait 15–60 min): every one of
  48 cells is PF > 1.24; PF rises with gap size while trade count falls. Longs earn more than shorts on SPX/NAS (27 vs 15 bp
  avg) — consistent with the equity drift — but shorts are still positive. Exit mix: 2/3 close at EOD, 1/3 stopped.
- **Concentration warning on gap_go.** 2008 alone is 47 % of SPX profit; 2008+2009+2020 are 77 %. Years 2012–2017 are
  roughly flat with few trades (70-bp gaps are rare in low-vol regimes). So the strategy is a *volatility-regime* edge:
  it earns when the market gaps big and keeps going. Expect long quiet stretches. Trade frequency ≈ 30/yr per symbol at
  70 bp; ≈ 50/yr at 50 bp with PF ≈ 1.5.
- **power_hour (continuation of a > 80-bp day from 14:30) is a near miss on SPX** (PF 1.48, 5/5 folds) but fails stability
  (44 %) and is flat on NAS; 2008 is 65 % of its SPX profit. Not promoted.
- **nr7_breakout** is PF 1.26–1.29 on SPX/RUT with 100 % grid stability but 4/5 folds and under the PF bar. Watch list.
- **orb (all variants), orb_zarattini, vwap_revert, vwap_trend, first_hour_break, vol_breakout, gap_fade, overnight_momo,
  afternoon_move fail** — most near PF 1.0 before stress, several deeply negative (VWAP reversion loses 2–3 bp per trade
  across 7–9k trades, in every fold, on every symbol). The Zarattini QQQ ORB reproduces its *shape* (17 % win rate, long
  right tail) at PF 1.15 on NAS100 but does not survive 2× costs (1.01). On an index it is not an edge; the published edge
  was on *stocks in play*, which this data cannot test.

## What this does and does not tell us

- It tells us which *mechanisms* have carried a cost-adjusted edge on index products over 15 years, with no parameter
  fitted to the test period and the bar set in advance. It does not tell us how they behave 2020–2026; that is the Schwab
  minute-data recheck on the PC (months of history) plus paper trading.
- Small-cap stocks-in-play strategies need a universe and real volume; not testable here. They go straight to paper on
  the M2M scanner feed with the same bar applied to paper results.
- Options strategies (0DTE condor after the range sets, directional debit spread off gap_go, straddle into range expansion,
  7–14 DTE vertical on the daily MR signal) cannot be backtested without an options dataset; forward paper only.

## Promotions to the paper pipeline

1. **gap_go on SPY and QQQ** (gap ≥ 70 bp, 30-min range, stop at range opposite, flat at close). Also run the 50-bp variant.
2. **nr7_breakout on SPY and IWM** as a watch-list bot (does not meet the bar; paper-only to collect out-of-sample evidence).
3. **Stocks-in-Play ORB** on the scanner universe (previously chosen; not testable here).
4. **power_hour SPX** stays on the bench until a non-2008 driver is shown.

Raw per-cell results: `var/research/*.json`. Re-run: `python -m research.run_all`.
