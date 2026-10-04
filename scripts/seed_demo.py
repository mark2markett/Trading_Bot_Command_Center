"""
Seed demo data into var/cc.db so the dashboard can be reviewed before real bots have history.
Clearly fictional: 5 bots, equity series, trades, fills, alerts, one degraded bot, one correlated pair.
Run: CC_VAR=<external sandbox> python scripts/seed_demo.py [--reset]
Writing to the repository's ledger requires the explicit --live-ledger override.
"""
from __future__ import annotations

import json
import os
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "cc_sdk"))
from cc_sdk.ledger import Ledger, db_path  # noqa: E402

from cc_sdk import Bot, BotManifest  # noqa: E402
from scripts.closed_loop_guard import validate_sandbox  # noqa: E402

random.seed(7)
NOW = datetime.now(timezone.utc)


def iso(d: datetime) -> str:
    return d.isoformat(timespec="seconds")


def main(reset: bool, *, live_ledger: bool = False) -> None:
    if not live_ledger:
        validate_sandbox(ROOT, os.getenv("CC_VAR"))
    p = db_path()
    if reset and p.exists():
        p.unlink()
        for ext in ("-wal", "-shm"):
            q = Path(str(p) + ext)
            if q.exists():
                q.unlink()
    (p.parent / "control").mkdir(parents=True, exist_ok=True)
    L = Ledger(p)

    specs = [
        dict(id="qqq_mr", name="QQQ Daily MR", mode="live", instrument="QQQ", strategy_line="RSI(2) mean reversion · daily",
             backtest={"win_rate": 0.73, "profit_factor": 1.9, "avg_win": 0.011, "avg_loss": -0.008, "trades_per_year": 6, "slippage_assumed": 0.01, "max_dd": 0.12},
             wr=0.58, n=12, equity=98_900, pos=(180, 604.21, 2)),
        dict(id="spy_mr", name="SPY Daily Mean Reversion", mode="paper", instrument="SPY", strategy_line="RSI(2) < 10 above SMA200 · exit SMA5 / 10 bars · 5% stop",
             backtest={"win_rate": 0.77, "profit_factor": 2.28, "avg_win": 0.0121, "avg_loss": -0.0081, "trades_per_year": 5, "slippage_assumed": 0.01, "max_dd": 0.116},
             wr=0.75, n=4, equity=101_854, pos=None),
        dict(id="spy_put_spread", name="SPY Short Put Spread", mode="live", instrument="SPY", strategy_line="Weekly premium · 30Δ · options",
             backtest={"win_rate": 0.82, "profit_factor": 1.6, "avg_win": 0.004, "avg_loss": -0.012, "trades_per_year": 48, "slippage_assumed": 0.01, "max_dd": 0.09},
             wr=0.8, n=20, equity=104_300, pos=(2, 1.42, 3)),
        dict(id="sector_trend", name="Sector Trend", mode="live", instrument="XL*", strategy_line="Monthly rotation · 11 sector ETFs",
             backtest={"win_rate": 0.55, "profit_factor": 1.8, "avg_win": 0.045, "avg_loss": -0.022, "trades_per_year": 24, "slippage_assumed": 0.01, "max_dd": 0.15},
             wr=0.56, n=16, equity=107_100, pos=(95, 248.77, 12)),
        dict(id="ibs_mr", name="IBS Daily MR", mode="paper", instrument="SPY", strategy_line="Internal bar strength · SPY · daily",
             backtest={"win_rate": 0.71, "profit_factor": 1.7, "avg_win": 0.0093, "avg_loss": -0.0085, "trades_per_year": 12, "slippage_assumed": 0.01, "max_dd": 0.19},
             wr=0.67, n=6, equity=99_100, pos=None),
    ]
    bots: dict[str, Bot] = {}
    for s in specs:
        m = BotManifest(id=s["id"], name=s["name"], version="1.2", strategy_line=s["strategy_line"], instrument=s["instrument"],
                        mode=s["mode"], cadence={"decide": "15:50", "reconcile": "09:45"}, backtest=s["backtest"])
        bots[s["id"]] = Bot(m, db_path=p)

    # equity series: 90 daily points per bot; qqq correlated with spy_mr
    base_noise = [random.gauss(0, 0.004) for _ in range(90)]
    for s in specs:
        eq = 100_000.0
        for i in range(90):
            day = NOW - timedelta(days=90 - i)
            if s["id"] in ("qqq_mr", "spy_mr"):
                r = base_noise[i] * (1.0 if s["id"] == "spy_mr" else 1.2) + random.gauss(0, 0.0015)
            else:
                r = random.gauss(0.0003, 0.004)
            eq *= 1 + r
            if i == 89:
                eq = s["equity"]
            L.x("INSERT INTO equity(bot_id,at,equity,source) VALUES(?,?,?,?)", (s["id"], iso(day.replace(hour=20, minute=5)), round(eq, 2), "bot"))
    # broker (account-level) equity: sum-ish, with a -3.1% drawdown from peak
    acct = 412_380.0
    peak = acct / (1 - 0.031)
    for i in range(90):
        day = NOW - timedelta(days=90 - i)
        v = 395_000 + (peak - 395_000) * min(1, i / 70) - (i > 70) * (peak - acct) * (i - 70) / 19
        L.x("INSERT INTO equity(bot_id,at,equity,source) VALUES(?,?,?,?)", ("qqq_mr", iso(day.replace(hour=20, minute=10)), round(v, 2), "broker"))
    L.x("UPDATE equity SET equity=410438.0 WHERE source='broker' AND id=(SELECT MAX(id) FROM equity WHERE source='broker')")
    L.x("INSERT INTO equity(bot_id,at,equity,source) VALUES(?,?,?,?)", ("qqq_mr", iso(NOW), 412_380.0, "broker"))
    for s in specs:  # today's bot-level mark so Day P&L shows per bot
        day_move = {"qqq_mr": -1106.0, "spy_put_spread": 184.0, "sector_trend": 2864.0}.get(s["id"], 0.0)
        L.x("INSERT INTO equity(bot_id,at,equity,source) VALUES(?,?,?,?)", (s["id"], iso(NOW), s["equity"] + day_move, "bot"))

    # trades + fills
    for s in specs:
        b = bots[s["id"]]
        for k in range(s["n"]):
            win = (k % 100) < round(s["wr"] * s["n"]) if s["id"] != "qqq_mr" else k < 5  # qqq: 5 of 12 -> drift
            entry_d = NOW - timedelta(days=random.randint(5, 85))
            exit_d = entry_d + timedelta(days=random.randint(1, 8))
            e = round(random.uniform(560, 680), 2)
            x = round(e * (1 + (abs(random.gauss(s["backtest"]["avg_win"], 0.004)) if win else -abs(random.gauss(abs(s["backtest"]["avg_loss"]), 0.004)))), 2)
            qty = random.randint(60, 180)
            L.trade(s["id"], entry_at=iso(entry_d), exit_at=iso(exit_d), qty=qty, entry_px=e, exit_px=x, bars=max(1, (exit_d - entry_d).days),
                    exit_reason=random.choice(["exit_sma", "exit_sma", "time_stop"]) if not win else "exit_sma", pnl=round((x - e) * qty, 2),
                    slippage=round(random.uniform(0.002, 0.012), 4))
            for side, px in (("BUY", e), ("SELL", x)):
                oid = L.order(s["id"], side=side, qty=qty, type_="MOC", symbol=s["instrument"], status="filled", reason="seed",
                              risk_result={"ok": True}, broker_order_id=f"seed-{k}-{side}", ref_price=px)
                L.x("UPDATE orders SET at=? WHERE id=?", (iso(entry_d if side == "BUY" else exit_d), oid))
                fid = L.fill(s["id"], oid, qty, round(px + random.uniform(0, 0.02), 2), px, 0.0035 * qty)
                L.x("UPDATE fills SET at=? WHERE id=?", (iso(entry_d if side == "BUY" else exit_d), fid))
        if s["pos"]:
            qty, avg, bars = s["pos"]
            b.set_position(s["instrument"], qty, avg, iso(NOW - timedelta(days=bars)), bars)
            oid = L.order(s["id"], side="SELL", qty=qty, type_="STOP", symbol=s["instrument"], status="sent", reason="protective stop",
                          risk_result={"ok": True}, broker_order_id="seed-stop", stop_price=round(avg * 0.95, 2), ref_price=avg)
        # heartbeats this morning
        for run in ("reconcile",):
            L.x("INSERT INTO heartbeats(bot_id,run,at,ok,detail) VALUES(?,?,?,?,?)",
                (s["id"], run, iso(NOW - timedelta(hours=2)), 1, ""))
        # decisions
        pxs = (s["pos"][1] * 1.004) if s["pos"] else 769.64
        b.L.decision(s["id"], "decide", {"price": round(pxs, 2), "rsi2": 86.8, "sma200": round(pxs * 0.937, 2), "sma5": round(pxs * 0.995, 2), "in_position": bool(s["pos"]), "bars_held": s["pos"][2] if s["pos"] else 0}, "HOLD" if s["pos"] else "NONE", "no exit signal" if s["pos"] else "no entry signal")
        b.L.decision(s["id"], "reconcile", {"last_bar": (NOW - timedelta(days=1)).date().isoformat(), "close": 769.64}, "RECONCILE", "ok")

    # alerts and audit
    L.alert("digest", "calendar", "Early close Fri 11/27 (1:00 pm). Daily bots: decide run moves to 12:50 pm.")
    L.alert("page", "token", "Schwab token expires in 1.8 days. Run `python bot.py auth`.")
    L.control("Mark", "limit", "portfolio.daily_loss_limit_pct", 0.025, 0.02, "tighter after Q3 review")
    L.control("Mark", "drill", "fleet", None, {"bots_stopped": 5, "seconds": 1.8}, "monthly kill drill · re-armed 16:34")
    L.control("riskd", "pause", "qqq_mr", None, {"paused": True}, "4 consecutive losses · resumed by Mark next day")
    print(json.dumps({"db": str(p), "bots": len(specs), "trades": L.one("SELECT COUNT(*) n FROM trades")["n"]}, indent=2))


if __name__ == "__main__":
    main("--reset" in sys.argv, live_ledger="--live-ledger" in sys.argv)
