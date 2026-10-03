"""Backtest engine: position walker with conservative fills, metrics, walk-forward folds, parameter grid, pass bar."""
from __future__ import annotations

import itertools
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from .data import Day

COST_BPS_SIDE = 1.0        # slippage + half spread per side, index ETF. Stress run uses 2.0.
PASS_BAR = {"pf": 1.3, "min_trades": 200, "folds": 5, "stable_frac": 0.6, "stable_pf": 1.1}


@dataclass
class Trade:
    date: pd.Timestamp
    side: int            # +1 long, -1 short
    entry_i: int
    exit_i: int
    entry_px: float
    exit_px: float
    reason: str

    def ret_bps(self, cost_bps_side: float) -> float:
        return self.side * (self.exit_px / self.entry_px - 1) * 1e4 - 2 * cost_bps_side


def walk(day: Day, side: int, signal_i: int, stop: float | None = None, target: float | None = None,
         exit_i: int | None = None, exit_fn: Callable[[int], bool] | None = None, reason_prefix: str = "") -> Trade | None:
    """Enter at the OPEN of the bar after the signal bar; exit on stop / target / exit_fn / time / close.
    Stops fill at the stop price, or at the bar open if the bar opened through it. Target same logic.
    exit_i is the bar index whose open is the time exit. Last bar always closes at its close."""
    i = signal_i + 1
    if i >= day.n:
        return None
    return walk_at(day, side, i, day.o[i], stop, target, exit_i, exit_fn, reason_prefix)


def walk_at(day: Day, side: int, i: int, px: float, stop: float | None = None, target: float | None = None,
            exit_i: int | None = None, exit_fn: Callable[[int], bool] | None = None, reason_prefix: str = "") -> Trade | None:
    """Same as walk() but with an explicit fill (bar i at price px), for stop-order style entries at a level."""
    if i >= day.n:
        return None
    last = day.n - 1
    end = min(exit_i if exit_i is not None else last, last)
    for k in range(i, end + 1):
        o, h, l = day.o[k], day.h[k], day.l[k]  # noqa: E741
        if stop is not None:
            if (side > 0 and o <= stop) or (side < 0 and o >= stop):
                return Trade(day.date, side, i, k, px, o, reason_prefix + "stop_gap")
            if (side > 0 and l <= stop) or (side < 0 and h >= stop):
                return Trade(day.date, side, i, k, px, stop, reason_prefix + "stop")
        if target is not None:
            if (side > 0 and o >= target) or (side < 0 and o <= target):
                return Trade(day.date, side, i, k, px, o, reason_prefix + "target_gap")
            if (side > 0 and h >= target) or (side < 0 and l <= target):
                return Trade(day.date, side, i, k, px, target, reason_prefix + "target")
        if exit_i is not None and k == exit_i:
            return Trade(day.date, side, i, k, px, o, reason_prefix + "time")
        if exit_fn is not None and k > i and exit_fn(k):
            if k + 1 <= last:
                return Trade(day.date, side, i, k + 1, px, day.o[k + 1], reason_prefix + "signal")
            return Trade(day.date, side, i, k, px, day.c[k], reason_prefix + "signal")
    return Trade(day.date, side, i, end, px, day.c[end], reason_prefix + "eod")


Strategy = Callable[[Day, dict[str, Any]], list[Trade]]


@dataclass
class Result:
    name: str
    symbol: str
    params: dict[str, Any]
    trades: list[Trade]
    cost_bps: float
    metrics: dict[str, float] = field(default_factory=dict)


def run(strategy: Strategy, days: list[Day], params: dict[str, Any]) -> list[Trade]:
    out: list[Trade] = []
    for d in days:
        out.extend(strategy(d, params))
    return out


def metrics(trades: list[Trade], days: list[Day], cost_bps: float) -> dict[str, float]:
    if not trades:
        return {"trades": 0, "pf": 0.0, "win_rate": 0.0, "avg_bps": 0.0, "sharpe": 0.0, "max_dd_pct": 0.0, "total_pct": 0.0}
    r = np.array([t.ret_bps(cost_bps) for t in trades])
    wins, losses = r[r > 0].sum(), -r[r <= 0].sum()
    pf = wins / losses if losses > 0 else float("inf")
    # daily P&L series (1x notional per trade, additive within a day), Sharpe annualized over trading days in sample
    by_day = pd.Series(r, index=[t.date for t in trades]).groupby(level=0).sum()
    all_days = pd.Series(0.0, index=pd.DatetimeIndex([d.date for d in days]))
    all_days.loc[by_day.index] = by_day.values
    daily = all_days / 1e4
    sharpe = float(daily.mean() / daily.std() * np.sqrt(252)) if daily.std() > 0 else 0.0
    eq = (1 + daily).cumprod()
    dd = (eq / eq.cummax() - 1).min()
    return {"trades": int(len(r)), "pf": round(float(pf), 3), "win_rate": round(float((r > 0).mean()), 3), "avg_bps": round(float(r.mean()), 2),
            "sharpe": round(sharpe, 2), "max_dd_pct": round(float(dd * 100), 2), "total_pct": round(float((eq.iloc[-1] - 1) * 100), 1)}


def folds(trades: list[Trade], days: list[Day], cost_bps: float, k: int = 5) -> list[float]:
    """Chronological k folds; returns net bps per fold (positive = fold made money)."""
    dates = [d.date for d in days]
    edges = [dates[int(len(dates) * j / k)] for j in range(k)] + [dates[-1] + pd.Timedelta(days=1)]
    out = []
    for a, b in zip(edges[:-1], edges[1:], strict=True):
        out.append(round(float(sum(t.ret_bps(cost_bps) for t in trades if a <= t.date < b)), 1))
    return out


def grid(params_grid: dict[str, list[Any]]) -> list[dict[str, Any]]:
    keys = list(params_grid)
    return [dict(zip(keys, vals, strict=True)) for vals in itertools.product(*[params_grid[k] for k in keys])]


def evaluate(name: str, symbol: str, strategy: Strategy, params_grid: dict[str, list[Any]], days: list[Day],
             cost_bps: float = COST_BPS_SIDE) -> dict[str, Any]:
    """Run the whole grid, pick the best by PF among sets with enough trades, and apply the pre-registered bar."""
    rows = []
    for p in grid(params_grid):
        tr = run(strategy, days, p)
        m = metrics(tr, days, cost_bps)
        m["folds_pos"] = sum(f > 0 for f in folds(tr, days, cost_bps)) if tr else 0
        rows.append({"params": p, **m, "_trades": tr})
    eligible = [r for r in rows if r["trades"] >= PASS_BAR["min_trades"]]
    best = max(eligible or rows, key=lambda r: r["pf"] if np.isfinite(r["pf"]) else 0)
    stable = float(np.mean([r["pf"] >= PASS_BAR["stable_pf"] for r in rows])) if rows else 0.0
    passed = (best["trades"] >= PASS_BAR["min_trades"] and best["pf"] >= PASS_BAR["pf"]
              and best["folds_pos"] == PASS_BAR["folds"] and stable >= PASS_BAR["stable_frac"])
    stress = metrics(best["_trades"], days, cost_bps * 2) if best["_trades"] else {"pf": 0.0}
    return {"name": name, "symbol": symbol, "best": {k: v for k, v in best.items() if k != "_trades"}, "stable_frac": round(stable, 2),
            "grid_size": len(rows), "pf_at_2x_cost": stress["pf"], "passed": bool(passed),
            "grid": [{k: v for k, v in r.items() if k != "_trades"} for r in rows]}
