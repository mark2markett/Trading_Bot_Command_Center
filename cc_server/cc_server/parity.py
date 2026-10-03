"""Live-vs-backtest parity. Bands come from the manifest's backtest stats and the live trade count so far."""
from __future__ import annotations

import math
import statistics
from typing import Any


def win_rate_band(p: float, n: int, z: float = 2.0) -> tuple[float, float]:
    """Binomial normal-approx band for an observed win rate after n trades."""
    if n <= 0:
        return (0.0, 1.0)
    se = math.sqrt(max(p * (1 - p), 1e-9) / n)
    return (max(0.0, p - z * se), min(1.0, p + z * se))


def evaluate(backtest: dict[str, Any], trades: list[dict[str, Any]], fills: list[dict[str, Any]]) -> dict[str, Any]:
    """Return verdict + the per-metric comparison the UI shows. Verdict: 'within' | 'drift' | 'n/a'."""
    n = len(trades)
    bt_wr = float(backtest.get("win_rate") or 0)
    bt_al = float(backtest.get("avg_loss") or 0)
    bt_slip = float(backtest.get("slippage_assumed") or 0.01)
    out: dict[str, Any] = {"trades": n, "backtest": backtest, "live": {}, "flags": [], "verdict": "n/a",
                           "sentence": "no trades yet"}
    if n == 0:
        return out
    wins = [t for t in trades if (t.get("pnl") or 0) > 0]
    losses = [t for t in trades if (t.get("pnl") or 0) <= 0]
    wr = len(wins) / n
    live: dict[str, Any] = {"win_rate": wr}
    rets = []
    for t in trades:
        if t.get("entry_px") and t.get("exit_px"):
            rets.append(t["exit_px"] / t["entry_px"] - 1)
    if wins:
        live["avg_win"] = statistics.mean([t["exit_px"] / t["entry_px"] - 1 for t in wins if t.get("entry_px")] or [0])
    if losses:
        live["avg_loss"] = statistics.mean([t["exit_px"] / t["entry_px"] - 1 for t in losses if t.get("entry_px")] or [0])
    if fills:
        live["slippage"] = statistics.mean([abs(f.get("slippage") or 0) for f in fills])
    out["live"] = live

    lo, hi = win_rate_band(bt_wr, n)
    out["win_rate_band"] = [lo, hi]
    if n >= 8 and not (lo <= wr <= hi):
        out["flags"].append(f"win rate {wr:.0%} vs {bt_wr:.0%}")
    if "avg_loss" in live and bt_al and n >= 8 and live["avg_loss"] < bt_al * 1.5:
        out["flags"].append(f"avg loss {live['avg_loss']:.2%} vs {bt_al:.2%}")
    if "slippage" in live and live["slippage"] > bt_slip * 2 and len(fills) >= 6:
        out["flags"].append(f"slippage {live['slippage']*100:.1f}¢ vs {bt_slip*100:.0f}¢ assumed")
    if n < 8:
        out["verdict"] = "within"
        out["sentence"] = f"{n} trades · too few to judge"
    elif out["flags"]:
        out["verdict"] = "drift"
        out["sentence"] = out["flags"][0]
    else:
        out["verdict"] = "within"
        out["sentence"] = "within band"
    return out


def expected_path(backtest: dict[str, Any], n_points: int, start_equity: float) -> dict[str, list[float]]:
    """Median and 5–95% band of equity after k trades, from backtest per-trade stats (normal approx on log returns)."""
    wr = float(backtest.get("win_rate") or 0.5)
    aw = float(backtest.get("avg_win") or 0.01)
    al = float(backtest.get("avg_loss") or -0.01)
    mu = wr * aw + (1 - wr) * al
    var = wr * aw * aw + (1 - wr) * al * al - mu * mu
    sd = math.sqrt(max(var, 1e-12))
    med, lo, hi = [], [], []
    for k in range(n_points):
        m = mu * k
        s = sd * math.sqrt(k)
        med.append(start_equity * (1 + m))
        lo.append(start_equity * (1 + m - 1.645 * s))
        hi.append(start_equity * (1 + m + 1.645 * s))
    return {"median": med, "lo": lo, "hi": hi}
