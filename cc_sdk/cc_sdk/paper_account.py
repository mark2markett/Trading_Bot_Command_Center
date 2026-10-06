"""One explicit paper account: starting capital + fleet realized + freshly marked unrealized P&L.

Never sums per-bot starting balances or labels simulated equity as broker equity.
Missing/stale marks make new-entry risk unavailable; exits remain permitted.
"""

from __future__ import annotations

import json
import math
from datetime import datetime
from zoneinfo import ZoneInfo

from .ledger import Ledger, now, now_iso
from .options import contract_multiplier

KEY = "paper_account"


def config(L: Ledger) -> dict | None:
    row = L.one("SELECT value_json FROM kv WHERE key=?", (KEY,))
    return json.loads(row["value_json"]) if row else None


def configure(L: Ledger, capital: float) -> None:
    if not math.isfinite(capital) or capital <= 0:
        raise ValueError("Paper starting capital must be finite and positive")
    bots = L.q("SELECT mode FROM bots")
    if not bots or any(b["mode"] != "paper" for b in bots):
        raise ValueError("Shared paper account requires an entirely paper fleet")
    existing = config(L)
    if existing:
        if existing["initial_capital"] != capital:
            raise ValueError("An account already exists; refusing to reset its capital or P&L")
        return
    if L.one("SELECT 1 FROM positions WHERE qty != 0"):
        raise ValueError("Initialize the account only while the fleet is flat")
    # Existing closed trades remain part of the paper account, rather than silently resetting losses.
    value = {"initial_capital": capital, "created_at": now_iso(), "model": "shared-paper-v1"}
    L.x("INSERT INTO kv(key,value_json,updated_at) VALUES(?,?,?)", (KEY, json.dumps(value), now_iso()))
    L.control("native-update", "configure_paper_account", "fleet", None, value, "User approved one shared paper account")
    record(L)


def mark(L: Ledger, symbol: str, price: float, at: datetime) -> None:
    if not math.isfinite(price) or price <= 0 or at.tzinfo is None:
        raise ValueError("Mark requires a positive price and an aware timestamp")
    L.x(
        "INSERT INTO paper_marks(symbol,price,at) VALUES(?,?,?) ON CONFLICT(symbol) DO UPDATE SET price=excluded.price,at=excluded.at",
        (symbol, price, at.isoformat()),
    )


def snapshot(L: Ledger) -> dict:
    with L.transaction(write=False):
        return _snapshot(L)


def _snapshot(L: Ledger) -> dict:
    c = config(L)
    result = {
        "ready": False,
        "source": "paper" if c else "none",
        "equity": None,
        "gross": None,
        "reason": "Paper account is unconfigured",
    }
    if not c:
        return result
    if L.one("SELECT 1 FROM bots WHERE mode != 'paper'"):
        return {**result, "reason": "Shared paper account cannot value a mixed/live fleet"}
    capital = float(c["initial_capital"])
    realized = float(L.one("SELECT COALESCE(SUM(pnl),0) AS pnl FROM trades")["pnl"])
    unrealized = gross = 0.0
    for p in L.q(
        "SELECT p.*,m.price AS mark_price,m.at AS mark_at FROM positions p LEFT JOIN paper_marks m ON p.symbol=m.symbol WHERE p.qty != 0"
    ):
        if p["mark_at"] is None:
            return {**result, "reason": f"Missing mark: {p['symbol']}"}
        age = (now() - datetime.fromisoformat(p["mark_at"])).total_seconds()
        price, entry = float(p["mark_price"]), p["avg_price"]
        if not -30 <= age <= 90 or entry is None or not math.isfinite(float(entry)) or entry <= 0:
            return {**result, "reason": f"Stale/invalid mark or cost basis: {p['symbol']}"}
        mult = contract_multiplier(p["symbol"])
        unrealized += p["qty"] * (price - entry) * mult
        gross += abs(p["qty"]) * price * mult
    for o in L.q(
        "SELECT symbol,qty,ref_price FROM orders WHERE status='sent' AND side IN ('BUY','SELL_SHORT','BUY_TO_OPEN','SELL_TO_OPEN')"
    ):
        if o["ref_price"] is None or not math.isfinite(float(o["ref_price"])) or o["ref_price"] <= 0:
            return {**result, "reason": "Pending opening order has no valid exposure price"}
        gross += abs(o["qty"]) * o["ref_price"] * contract_multiplier(o["symbol"])
    equity = capital + realized + unrealized
    if not math.isfinite(equity) or equity <= 0:
        return {**result, "reason": "Paper account equity is nonpositive or invalid"}
    history = L.q("SELECT at,equity FROM paper_equity ORDER BY id")
    peak = max([capital, equity] + [float(r["equity"]) for r in history])
    today = now().astimezone(ZoneInfo("America/New_York")).date()
    prior = [
        float(r["equity"])
        for r in history
        if datetime.fromisoformat(r["at"]).astimezone(ZoneInfo("America/New_York")).date() < today
    ]
    base = prior[-1] if prior else capital
    return {
        **result,
        "drawdown": (peak - equity) / peak,
        "day_pnl": equity - base,
        "day_pct": (equity - base) / base,
        "peak": peak,
        "ready": True,
        "equity": equity,
        "gross": gross,
        "realized": realized,
        "unrealized": unrealized,
        "initial_capital": capital,
        "reason": "Fresh shared paper account valuation",
    }


def record(L: Ledger) -> dict:
    value = snapshot(L)
    if value["ready"]:
        L.x("INSERT INTO paper_equity(at,equity) VALUES(?,?)", (now_iso(), value["equity"]))
    return value
