"""Options verdict (M7.4): did the spread add anything over the same delta held in shares?

Option P&L measured on its own cannot tell an edge from leverage on the underlying's move — M2M found ~30 option
backtests that looked profitable and were levered long beta. So the verdict reports, per bot:
- profit factor when the underlying went up during the trade vs when it went down;
- spread P&L minus the P&L of shares holding the spread's entry delta (the "excess");
and says in plain words whether the spread beat the shares.
"""
from __future__ import annotations

from typing import Any

MIN_TRADES = 20


def _pf(pnls: list[float]) -> float | None:
    wins = sum(p for p in pnls if p > 0)
    losses = -sum(p for p in pnls if p < 0)
    if not pnls:
        return None
    return float("inf") if losses == 0 else round(wins / losses, 2)


def options_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """rows: option_trades rows (spread_pnl, share_equiv_pnl, und_entry, und_exit)."""
    n = len(rows)
    spread = [float(r["spread_pnl"]) for r in rows]
    shares = [float(r["share_equiv_pnl"]) for r in rows]
    up = [float(r["spread_pnl"]) for r in rows if float(r["und_exit"]) > float(r["und_entry"])]
    down = [float(r["spread_pnl"]) for r in rows if float(r["und_exit"]) <= float(r["und_entry"])]
    excess = round(sum(spread) - sum(shares), 2)
    beat = sum(1 for s, h in zip(spread, shares, strict=True) if s > h)
    if n < MIN_TRADES:
        verdict = f"Too few trades to judge ({n} of {MIN_TRADES} needed)."
    elif excess > 0:
        verdict = f"Beating the same delta held in shares by ${excess:,.0f} over {n} trades ({beat} of {n} trades better)."
    else:
        verdict = (f"Not beating the same delta held in shares (${excess:,.0f} over {n} trades): "
                   "this is the signal with leverage, not an options edge.")
    return {"trades": n, "spread_pnl": round(sum(spread), 2), "share_equiv_pnl": round(sum(shares), 2),
            "excess_vs_shares": excess, "trades_beating_shares": beat, "pf_all": _pf(spread),
            "pf_underlying_up": _pf(up), "pf_underlying_down": _pf(down), "n_up": len(up), "n_down": len(down),
            "verdict": verdict}
