import math, random, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import strategy as S


def test_rsi_matches_pandas_ewm():
    """Wilder RSI == pandas ewm(alpha=1/n, adjust=False) RSI, the same formula TradingView uses."""
    import pandas as pd
    random.seed(1)
    px = [100.0]
    for _ in range(500):
        px.append(px[-1] * (1 + random.gauss(0, 0.01)))
    s = pd.Series(px)
    d = s.diff()
    g = d.clip(lower=0); l = -d.clip(upper=0)
    ag = g.ewm(alpha=1/2, adjust=False).mean(); al = l.ewm(alpha=1/2, adjust=False).mean()
    ref = (100 - 100 / (1 + ag / al)).iloc[-1]
    assert math.isclose(S.rsi_wilder(px, 2), ref, rel_tol=1e-9)


def test_entry_and_exit_rules():
    p = S.Params()
    base = [100 + i * 0.1 for i in range(250)]          # uptrend, close > SMA200
    dip = base + [base[-1] * 0.98, base[-1] * 0.965]     # two down days -> RSI2 near 0
    snap = S.snapshot(dip, p)
    assert snap.rsi < 10 and snap.close > snap.sma_trend
    assert S.entry_signal(snap, p)
    # exit when close pops above SMA5
    bounce = dip + [dip[-1] * 1.03]
    s2 = S.snapshot(bounce, p)
    assert S.exit_signal(s2, 1, p) == "exit_sma"
    # time stop
    assert S.exit_signal(S.snapshot(dip, p), 10, p) == "time_stop"
    assert S.exit_signal(S.snapshot(dip, p), 1, p) is None
    assert S.stop_price(500.0, p) == 475.0


def test_no_entry_below_trend():
    p = S.Params()
    down = [200 - i * 0.3 for i in range(250)] + [120, 118]
    assert not S.entry_signal(S.snapshot(down, p), p)
