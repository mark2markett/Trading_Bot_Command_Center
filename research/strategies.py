"""Twelve intraday rule sets, each a pure function (Day, params) -> list[Trade]. No state, no I/O.
Every rule: signal on bar close, fill at next bar open (or at a level for stop-order entries), flat by the close."""
from __future__ import annotations

from typing import Any

import numpy as np

from .data import Day
from .engine import Trade, walk, walk_at

P = dict[str, Any]
NOON, H13, H14, H1430, H15, H1530 = 720, 780, 840, 870, 900, 930


def _vwap(d: Day) -> np.ndarray:
    tp = (d.h + d.l + d.c) / 3
    v = np.where(d.v > 0, d.v, 1.0)
    return np.cumsum(tp * v) / np.cumsum(v)


def _first_break(d: Day, start: int, hi: float, lo: float, allow: tuple[int, ...] = (1, -1)) -> tuple[int, int] | None:
    for k in range(start, d.n - 1):
        if 1 in allow and d.c[k] > hi:
            return k, 1
        if -1 in allow and d.c[k] < lo:
            return k, -1
    return None


def _level_fill(d: Day, start: int, level: float, side: int) -> tuple[int, float] | None:
    """Stop-order entry: first bar from `start` that trades through `level`; fills at level or the worse open."""
    for k in range(start, d.n - 1):
        if side > 0 and d.h[k] >= level:
            return k, max(d.o[k], level)
        if side < 0 and d.l[k] <= level:
            return k, min(d.o[k], level)
    return None


# 1. Opening-range breakout -----------------------------------------------------------------------------------
def orb(d: Day, p: P) -> list[Trade]:
    n = d.idx_at(570 + p["range_min"])
    if n < 2 or n >= d.n - 5:
        return []
    hi, lo = d.h[:n].max(), d.l[:n].min()
    if p["vol_filter"] and d.vol_profile is not None:
        base = np.nansum(d.vol_profile[: p["range_min"]])
        if base <= 0 or d.v[:n].sum() / base < 1.0:
            return []
    b = _first_break(d, n, hi, lo)
    if b is None:
        return []
    k, side = b
    rng = hi - lo
    stop = (lo if side > 0 else hi) if p["stop"] == "range" else d.o[k + 1] - side * 0.1 * d.atr14
    risk = abs(d.o[k + 1] - stop) if k + 1 < d.n else rng
    target = d.o[k + 1] + side * p["target_r"] * risk if p["target_r"] else None
    t = walk(d, side, k, stop=stop, target=target)
    return [t] if t else []


ORB_GRID = {"range_min": [5, 15, 30], "stop": ["range", "atr10"], "target_r": [None, 2, 5], "vol_filter": [False, True]}


# 2. Zarattini/Aziz ORB: direction of the first candle, stop = fraction of daily ATR, optional 10R target -------
def orb_zarattini(d: Day, p: P) -> list[Trade]:
    n = d.idx_at(570 + p["first_min"])
    if n < 1 or n >= d.n - 5:
        return []
    move = d.c[n - 1] - d.o[0]
    if move == 0:
        return []
    side = 1 if move > 0 else -1
    px = d.o[n]
    stop = px - side * p["stop_atr"] * d.atr14
    target = px + side * p["target_r"] * abs(px - stop) if p["target_r"] else None
    t = walk_at(d, side, n, px, stop=stop, target=target)
    return [t] if t else []


ORB_Z_GRID = {"first_min": [5, 15], "stop_atr": [0.05, 0.1, 0.2], "target_r": [None, 10]}


# 3. VWAP mean reversion ---------------------------------------------------------------------------------------
def vwap_revert(d: Day, p: P) -> list[Trade]:
    vw = _vwap(d)
    dev = d.c - vw
    out: list[Trade] = []
    k = d.idx_at(570 + p["start_min"])
    while k < d.n - 2 and len(out) < p["max_trades"]:
        sd = dev[:k].std()
        if sd > 0 and abs(dev[k]) > p["k"] * sd:
            side = -1 if dev[k] > 0 else 1
            stop = d.o[k + 1] - side * p["stop_mult"] * abs(dev[k])
            t = walk(d, side, k, stop=stop, exit_fn=lambda j, s=side: s * (d.c[j] - vw[j]) >= 0)
            if t is None:
                break
            out.append(t)
            k = t.exit_i + 1
        else:
            k += 1
    return out


VWAP_R_GRID = {"k": [1.5, 2.0, 2.5, 3.0], "start_min": [30, 60], "stop_mult": [1.0, 2.0], "max_trades": [3]}


# 4. VWAP trend pullback ---------------------------------------------------------------------------------------
def vwap_trend(d: Day, p: P) -> list[Trade]:
    vw = _vwap(d)
    out: list[Trade] = []
    k = d.idx_at(570 + p["start_min"])
    cb = p["confirm_bars"]
    k = max(k, cb)
    while k < d.n - 2 and len(out) < 2:
        seg = d.c[k - cb:k] - vw[k - cb:k]
        if (seg > 0).all() and d.l[k] <= vw[k] * (1 + p["band_bps"] / 1e4) and d.c[k] > vw[k]:
            side = 1
        elif (seg < 0).all() and d.h[k] >= vw[k] * (1 - p["band_bps"] / 1e4) and d.c[k] < vw[k]:
            side = -1
        else:
            k += 1
            continue
        stop = d.l[k - 5:k + 1].min() if side > 0 else d.h[k - 5:k + 1].max()
        t = walk(d, side, k, stop=stop, exit_fn=lambda j, s=side: s * (d.c[j] - vw[j]) < 0)
        if t is None:
            break
        out.append(t)
        k = t.exit_i + 1
    return out


VWAP_T_GRID = {"band_bps": [0, 5], "confirm_bars": [15, 30], "start_min": [30, 60]}


# 5. Gap-and-go ------------------------------------------------------------------------------------------------
def gap_go(d: Day, p: P) -> list[Trade]:
    gap = (d.o[0] / d.prev_close - 1) * 1e4
    if abs(gap) < p["gap_bps"]:
        return []
    side = 1 if gap > 0 else -1
    n = d.idx_at(570 + p["wait_min"])
    if n >= d.n - 5:
        return []
    hi, lo = d.h[:n].max(), d.l[:n].min()
    b = _first_break(d, n, hi, lo, allow=(side,))
    if b is None:
        return []
    k, _ = b
    t = walk(d, side, k, stop=lo if side > 0 else hi)
    return [t] if t else []


GAP_GO_GRID = {"gap_bps": [20, 40, 70], "wait_min": [5, 15, 30]}


# 6. Gap fade --------------------------------------------------------------------------------------------------
def gap_fade(d: Day, p: P) -> list[Trade]:
    gap = (d.o[0] / d.prev_close - 1) * 1e4
    if not (p["lo_bps"] <= abs(gap) <= p["hi_bps"]):
        return []
    side = -1 if gap > 0 else 1
    size = abs(d.o[0] - d.prev_close)
    t = walk(d, side, 0, stop=d.o[1] - side * p["stop_mult"] * size, target=d.prev_close)
    return [t] if t else []


GAP_FADE_GRID = {"lo_bps": [10, 20, 30], "hi_bps": [60, 100, 150], "stop_mult": [1.0, 2.0]}


# 7. First-hour range break -------------------------------------------------------------------------------------
def first_hour_break(d: Day, p: P) -> list[Trade]:
    n = d.idx_at(570 + p["range_min"])
    if n >= d.n - 5:
        return []
    hi, lo = d.h[:n].max(), d.l[:n].min()
    b = _first_break(d, n, hi, lo)
    if b is None:
        return []
    k, side = b
    stop = (hi + lo) / 2 if p["stop"] == "mid" else (lo if side > 0 else hi)
    risk = abs(d.o[k + 1] - stop)
    target = d.o[k + 1] + side * p["target_r"] * risk if p["target_r"] else None
    t = walk(d, side, k, stop=stop, target=target)
    return [t] if t else []


FHB_GRID = {"range_min": [60, 90], "stop": ["mid", "range"], "target_r": [None, 1.5]}


# 8. NR7 breakout of the prior day's range ---------------------------------------------------------------------
def nr7_breakout(d: Day, p: P) -> list[Trade]:
    if not d.nr7:
        return []
    b = _first_break(d, 0, d.prev_high, d.prev_low)
    if b is None:
        return []
    k, side = b
    mid = (d.prev_high + d.prev_low) / 2
    stop = mid if p["stop"] == "mid" else d.o[k + 1] - side * 0.25 * d.atr14
    risk = abs(d.o[k + 1] - stop)
    target = d.o[k + 1] + side * p["target_r"] * risk if p["target_r"] else None
    t = walk(d, side, k, stop=stop, target=target)
    return [t] if t else []


NR7_GRID = {"stop": ["mid", "atr25"], "target_r": [None, 2]}


# 9. Overnight-return momentum into the open ------------------------------------------------------------------
def overnight_momo(d: Day, p: P) -> list[Trade]:
    gap = (d.o[0] / d.prev_close - 1) * 1e4
    if abs(gap) < p["min_bps"] or gap == 0:
        return []
    side = (1 if gap > 0 else -1) * (-1 if p["reverse"] else 1)
    exit_i = d.idx_at(570 + p["hold_min"])
    t = walk(d, side, 0, stop=d.o[1] - side * 0.3 * d.atr14, exit_i=exit_i)
    return [t] if t else []


ON_GRID = {"hold_min": [15, 30, 60], "min_bps": [0, 10, 30], "reverse": [False, True]}


# 10. Late-day momentum / reversal ---------------------------------------------------------------------------
def power_hour(d: Day, p: P) -> list[Trade]:
    k = d.idx_at(p["start_mod"])
    if k >= d.n - 5:
        return []
    ret = (d.c[k] / d.o[0] - 1) * 1e4
    if abs(ret) < p["t_bps"]:
        return []
    side = (1 if ret > 0 else -1) * (-1 if p["reverse"] else 1)
    t = walk(d, side, k, stop=d.o[k + 1] - side * 0.25 * d.atr14)
    return [t] if t else []


PH_GRID = {"start_mod": [H1430, H15, H1530], "t_bps": [20, 40, 80], "reverse": [False, True]}


# 11. Volatility breakout (Williams): open ± k × prior range, stop-order entry -------------------------------
def vol_breakout(d: Day, p: P) -> list[Trade]:
    k = p["k"]
    up, dn = d.o[0] + k * d.prev_range, d.o[0] - k * d.prev_range
    fu, fd = _level_fill(d, 1, up, 1), _level_fill(d, 1, dn, -1)
    cands = [(f, s) for f, s in ((fu, 1), (fd, -1)) if f]
    if not cands:
        return []
    (i, px), side = min(cands, key=lambda c: c[0][0])
    stop = d.o[0] if p["stop"] == "open" else (dn if side > 0 else up)
    t = walk_at(d, side, i, px, stop=stop)
    return [t] if t else []


VB_GRID = {"k": [0.3, 0.5, 0.7], "stop": ["open", "opp"]}


# 12. Afternoon fade / continuation of a large intraday move ------------------------------------------------
def afternoon_move(d: Day, p: P) -> list[Trade]:
    k = d.idx_at(p["check_mod"])
    if k >= d.n - 5:
        return []
    move = d.c[k] - d.o[0]
    if abs(move) < p["x_atr"] * d.atr14:
        return []
    side = (-1 if move > 0 else 1) * (-1 if p["continue"] else 1)
    t = walk(d, side, k, stop=d.o[k + 1] - side * p["y_atr"] * d.atr14)
    return [t] if t else []


AM_GRID = {"check_mod": [NOON, H13, H14], "x_atr": [0.5, 0.75, 1.0], "y_atr": [0.25, 0.5], "continue": [False, True]}


REGISTRY = {
    "orb": (orb, ORB_GRID, "Opening-range breakout (5/15/30 min), stop at range or 10% ATR, optional R target, optional volume filter"),
    "orb_zarattini": (orb_zarattini, ORB_Z_GRID, "Zarattini/Aziz ORB: first-candle direction, stop = fraction of daily ATR, optional 10R target"),
    "vwap_revert": (vwap_revert, VWAP_R_GRID, "Fade k-sigma deviations from VWAP, exit at VWAP"),
    "vwap_trend": (vwap_trend, VWAP_T_GRID, "Trend side held vs VWAP, enter on pullback touch, exit on VWAP cross"),
    "gap_go": (gap_go, GAP_GO_GRID, "Gap continuation: break of the first N-min range in the gap direction"),
    "gap_fade": (gap_fade, GAP_FADE_GRID, "Fade small gaps toward the prior close"),
    "first_hour_break": (first_hour_break, FHB_GRID, "Break of the 60/90-min range, afternoon continuation"),
    "nr7_breakout": (nr7_breakout, NR7_GRID, "Break of prior-day range after a narrowest-of-7 day"),
    "overnight_momo": (overnight_momo, ON_GRID, "Trade the overnight direction (or its reverse) for the first 15–60 min"),
    "power_hour": (power_hour, PH_GRID, "Late-day continuation or reversal of the day's move"),
    "vol_breakout": (vol_breakout, VB_GRID, "Williams volatility breakout: open ± k × prior range, stop at open"),
    "afternoon_move": (afternoon_move, AM_GRID, "Fade or continue a > x·ATR move at noon/13:00/14:00"),
}
