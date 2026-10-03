"""HTTP API. Read endpoints aggregate the ledger; control endpoints write audit first, then act."""
from __future__ import annotations

import secrets
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from cc_sdk.control import Control, control_dir
from cc_sdk.ledger import Ledger, var_dir
from cc_sdk.manifest import DEFAULT_LIMITS, PORTFOLIO_DEFAULTS
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import calendar as cal
from . import db, parity, riskd
from .alerts import Alerter

ET = ZoneInfo("America/New_York")
router = APIRouter(prefix="/api")
_L: Ledger | None = None
_alerter: Alerter | None = None
_confirm: dict[str, str] = {}   # action -> word, single use

WORDS = ["anchor", "basalt", "cobalt", "delta", "ember", "falcon", "garnet", "harbor", "iron", "juniper", "kestrel", "lumen"]


def L() -> Ledger:
    global _L
    if _L is None:
        _L = Ledger()
    return _L


def alerter() -> Alerter:
    global _alerter
    if _alerter is None:
        _alerter = Alerter(L())
    return _alerter


def _bot_summary(b: dict[str, Any], par: dict[str, Any]) -> dict[str, Any]:
    hb = db.last_heartbeat(L(), b["id"])
    pos = db.position(L(), b["id"])
    eq = db.equity_series(L(), b["id"], days=5)
    day = 0.0
    if len(eq) >= 2:
        today = datetime.now(ET).date().isoformat()
        prev = [v for at, v in eq if not at.startswith(today)]
        base = prev[-1] if prev else eq[0][1]
        day = eq[-1][1] - base
    pe = L().bot_peak_and_last_equity(b["id"])
    dd = 0.0 if not pe or pe[0] <= 0 else (pe[0] - pe[1]) / pe[0]
    c = Control(b["id"])
    return {
        "id": b["id"], "name": b["name"], "strategy_line": b["strategy_line"], "mode": b["mode"], "version": b["version"],
        "instrument": b["instrument"], "status": b["status"], "cadence": b.get("cadence", {}),
        "position": pos, "day_pnl": day, "drawdown": dd, "equity": pe[1] if pe else None,
        "parity": {"verdict": par.get("verdict", "n/a"), "sentence": par.get("sentence", "")},
        "heartbeat": hb, "flags": {"killed": c.killed(), "paused": c.entries_paused(), "flatten": c.flatten_requested()},
        "rejected_24h": db.rejected_orders_24h(L(), b["id"]),
    }


def _sort_key(s: dict[str, Any]) -> tuple:
    rank = {"degraded": 0, "running": 1, "paused": 2, "killed": 3}.get(s["status"], 4)
    in_pos = 0 if (s["position"] and s["position"]["qty"]) else 1
    live = 0 if s["mode"] == "live" else 1
    return (rank, in_pos, live, s["name"])


@router.get("/fleet")
def fleet() -> dict[str, Any]:
    par = riskd.parity_all(L())
    bots = sorted((_bot_summary(b, par.get(b["id"], {})) for b in db.bot_rows(L())), key=_sort_key)
    dd = riskd.portfolio_drawdown(L())
    counts = {"running": 0, "degraded": 0, "paused": 0, "killed": 0}
    for b in bots:
        counts[b["status"]] = counts.get(b["status"], 0) + 1
    now_et = datetime.now(ET)
    schedule = []
    for b in bots:
        for run, hhmm in (b["cadence"] or {}).items():
            t = "12:50" if run == "decide" and cal.is_early_close(now_et.date()) else hhmm
            done = bool(L().one("SELECT 1 FROM heartbeats WHERE bot_id=? AND run=? AND ok=1 AND at>=?",
                                (b["id"], run, now_et.replace(hour=0, minute=0, second=0).astimezone(timezone.utc).isoformat())))
            schedule.append({"time": t, "bot": b["name"], "run": run, "done": done})
    schedule.sort(key=lambda s: s["time"])
    tok = riskd.token_days_left()
    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "equity": dd["equity"], "equity_series": db.broker_equity_series(L(), 90),
        "day": riskd.day_pnl(L()), "daily_loss_limit_pct": riskd.plim(L(), "daily_loss_limit_pct"),
        "exposure": riskd.gross_exposure(L()),
        "drawdown": {**dd, "pause": riskd.plim(L(), "dd_pause_pct"), "flatten": riskd.plim(L(), "dd_flatten_pct"), "kill": riskd.plim(L(), "dd_kill_pct")},
        "counts": counts, "bots": bots,
        "attention": db.alerts(L(), 12, unacked_only=True),
        "correlation": riskd.correlation(L()),
        "schedule": schedule, "open_orders": db.open_orders(L()), "fills": db.fills(L(), None, 8),
        "market_open": cal.is_trading_day(now_et.date()) and (9, 30) <= (now_et.hour, now_et.minute) < tuple(map(int, cal.close_time_str(now_et.date()).split(":"))),
        "killed": (control_dir() / "KILL").exists(), "entries_paused": (control_dir() / "PAUSE_ENTRIES").exists(),
        "token": tok, "next_early_close": str(cal.next_early_close(now_et.date())),
    }


@router.get("/bots")
def bots() -> list[dict[str, Any]]:
    par = riskd.parity_all(L())
    return sorted((_bot_summary(b, par.get(b["id"], {})) for b in db.bot_rows(L())), key=_sort_key)


@router.get("/bots/{bot_id}")
def bot(bot_id: str) -> dict[str, Any]:
    b = next((x for x in db.bot_rows(L()) if x["id"] == bot_id), None)
    if not b:
        raise HTTPException(404, "no such bot")
    tr = db.trades(L(), bot_id)
    fl = db.fills(L(), bot_id, 200)
    par = parity.evaluate(b.get("backtest") or {}, tr, fl)
    eq = db.equity_series(L(), bot_id)
    start = eq[0][1] if eq else 100_000.0
    band = parity.expected_path(b.get("backtest") or {}, max(len(tr) + 1, 2), start)
    limits = {**DEFAULT_LIMITS, **(b.get("limits") or {}), **db.limits(L(), bot_id)}
    today = datetime.now(timezone.utc).date().isoformat()
    orders_today = len(L().orders_today(bot_id, today))
    recent = L().recent_trades(bot_id, int(limits["max_consecutive_losses"]))
    consec = 0
    for r in recent:
        if (r["pnl"] or 0) < 0:
            consec += 1
        else:
            break
    s = _bot_summary(b, par)
    return {**s, "backtest": b.get("backtest"), "limits": limits, "parity_detail": par, "equity_series": eq,
            "expected": band, "trades": tr, "fills": fl[:50], "decisions": db.decisions(L(), bot_id),
            "usage": {"orders_today": orders_today, "consecutive_losses": consec},
            "stop_price": (s["position"]["avg_price"] * 0.95) if s["position"] and s["position"].get("avg_price") else None}


@router.get("/risk")
def risk() -> dict[str, Any]:
    dd = riskd.portfolio_drawdown(L())
    lim = {**PORTFOLIO_DEFAULTS, **db.limits(L(), "portfolio")}
    exp = riskd.gross_exposure(L())
    today = datetime.now(timezone.utc).date().isoformat()
    peak_order = L().one("SELECT MAX(qty*ref_price) v FROM orders WHERE at LIKE ?", (today + "%",))
    rejected = L().one("SELECT COUNT(*) n FROM orders WHERE status='rejected' AND at LIKE ?", (today + "%",))
    mismatches = 0
    last_test = db.kv_get(L(), "alert_test")
    drills = db.controls(L(), 200)
    last_drill = next((c for c in drills if c["action"] == "drill"), None)
    return {
        "killed": (control_dir() / "KILL").exists(), "entries_paused": (control_dir() / "PAUSE_ENTRIES").exists(),
        "kill_flag": Control.read_flag(control_dir() / "KILL"), "drawdown": dd, "limits": lim, "exposure": exp,
        "checks": [
            {"check": "Max order size (fat finger)", "limit": f"${DEFAULT_LIMITS['max_order_usd']:,.0f} / {DEFAULT_LIMITS['max_order_qty']:,} sh",
             "peak": f"${(peak_order['v'] or 0):,.0f}", "on_breach": "reject + alert"},
            {"check": "Max gross exposure", "limit": f"{lim['max_gross_exposure']:.2f}× equity", "peak": f"{exp['ratio']:.2f}×", "on_breach": "reject new entries"},
            {"check": "Price collar vs last quote", "limit": f"±{DEFAULT_LIMITS['price_collar_pct']:.1%}", "peak": "—", "on_breach": "reject + alert"},
            {"check": "Orders per bot per day", "limit": f"{DEFAULT_LIMITS['max_orders_per_day']} (daily bots)", "peak": "—", "on_breach": "disable bot until re-enabled"},
            {"check": "Stale market data", "limit": f"quote age ≤ {DEFAULT_LIMITS['stale_quote_s']} s", "peak": "—", "on_breach": "skip run + alert"},
            {"check": "Duplicate order guard", "limit": "same bot + side + day", "peak": f"{rejected['n']} rejected today", "on_breach": "reject"},
            {"check": "Position = state reconciliation", "limit": "before every decide", "peak": f"{mismatches} mismatches", "on_breach": "adopt broker, alert"},
        ],
        "dependencies": {"riskd_last": db.kv_get(L(), "riskd_last"), "token": riskd.token_days_left(),
                         "calendar_loaded": True, "host": riskd.host_info(), "alert_test": last_test,
                         "bots": len(db.bot_rows(L()))},
        "audit": db.controls(L(), 40), "last_drill": last_drill,
    }


@router.get("/alerts")
def alerts(limit: int = 50) -> list[dict[str, Any]]:
    return db.alerts(L(), limit)


@router.post("/alerts/{alert_id}/ack")
def ack(alert_id: int) -> dict[str, Any]:
    L().x("UPDATE alerts SET acknowledged_at=? WHERE id=?", (datetime.now(timezone.utc).isoformat(), alert_id))
    return {"ok": True}


@router.post("/alerts/test")
def alert_test() -> dict[str, Any]:
    return alerter().test()


@router.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "db": str(db_path_safe()), "riskd_last": db.kv_get(L(), "riskd_last"), "control_dir_ok": control_dir().is_dir()}


def db_path_safe() -> Path:
    return L().path


# ---------------------------------------------------------------------------
class ConfirmReq(BaseModel):
    word: str | None = None
    note: str = ""
    actor: str = "operator"


@router.post("/controls/confirm/{action}")
def get_confirm_word(action: str) -> dict[str, str]:
    w = secrets.choice(WORDS)
    _confirm[action] = w
    return {"action": action, "word": w}


def _check_word(action: str, word: str | None) -> None:
    expected = _confirm.pop(action, None)
    if not expected or word != expected:
        raise HTTPException(400, "confirmation word missing or wrong")


def _trigger_reconcile(bot_id: str) -> None:
    """Ask the bot to run its own reconcile so IT flattens through ITS broker client. Best effort."""
    bots_dir = var_dir().parent / "bots"
    for p in bots_dir.glob("*/bot.py"):
        if p.parent.name.startswith("_"):
            continue
        try:
            subprocess.Popen([sys.executable, str(p), "reconcile"], cwd=str(p.parent))
        except Exception:  # noqa: BLE001
            pass


@router.post("/controls/kill_all")
def kill_all(req: ConfirmReq) -> dict[str, Any]:
    _check_word("kill_all", req.word)
    cdir = control_dir(); cdir.mkdir(parents=True, exist_ok=True)
    L().control(req.actor, "kill_all", "fleet", {"killed": (cdir / "KILL").exists()}, {"killed": True}, req.note)  # audit first
    Control.write_flag(cdir / "KILL", {"actor": req.actor, "reason": req.note or "manual"})
    for b in db.bot_rows(L()):
        Control.write_flag(cdir / f"{b['id']}.flatten", {"actor": req.actor, "reason": "kill"})
        L().set_bot_status(b["id"], "killed")
    L().alert("page", "kill", f"KILL ALL by {req.actor}: {req.note or 'manual'}")
    _trigger_reconcile("*")
    return {"ok": True, "killed": True}


@router.post("/controls/flatten_all")
def flatten_all(req: ConfirmReq) -> dict[str, Any]:
    _check_word("flatten_all", req.word)
    cdir = control_dir()
    targets = [b["id"] for b in db.bot_rows(L())]
    L().control(req.actor, "flatten", ",".join(targets), None, {"flatten": True}, req.note)
    for t in targets:
        Control.write_flag(cdir / f"{t}.flatten", {"actor": req.actor, "reason": req.note or "manual"})
    L().alert("page", "flatten", f"Flatten all by {req.actor}")
    _trigger_reconcile("*")
    return {"ok": True}


@router.post("/controls/pause_entries")
def pause_entries(req: ConfirmReq) -> dict[str, Any]:
    cdir = control_dir(); cdir.mkdir(parents=True, exist_ok=True)
    L().control(req.actor, "pause_entries", "fleet", {"paused": (cdir / "PAUSE_ENTRIES").exists()}, {"paused": True}, req.note)
    Control.write_flag(cdir / "PAUSE_ENTRIES", {"actor": req.actor, "reason": req.note or "manual"})
    return {"ok": True}


@router.post("/controls/resume_entries")
def resume_entries(req: ConfirmReq) -> dict[str, Any]:
    p = control_dir() / "PAUSE_ENTRIES"
    L().control(req.actor, "resume_entries", "fleet", {"paused": p.exists()}, {"paused": False}, req.note)
    if p.exists():
        p.unlink()
    return {"ok": True}


@router.post("/controls/rearm")
def rearm(req: ConfirmReq) -> dict[str, Any]:
    _check_word("rearm", req.word)
    riskd.rearm(L(), req.actor, req.note)
    for b in db.bot_rows(L()):
        L().set_bot_status(b["id"], Control(b["id"]).status_word())
    return {"ok": True, "killed": False}


@router.post("/controls/bot/{bot_id}/{action}")
def bot_control(bot_id: str, action: str, req: ConfirmReq) -> dict[str, Any]:
    if not any(b["id"] == bot_id for b in db.bot_rows(L())):
        raise HTTPException(404, "no such bot")
    cdir = control_dir(); cdir.mkdir(parents=True, exist_ok=True)
    if action in ("flatten", "kill"):
        _check_word(f"{action}:{bot_id}", req.word)
    if action == "pause":
        L().control(req.actor, "pause", bot_id, None, {"paused": True}, req.note)
        Control.write_flag(cdir / f"{bot_id}.pause", {"actor": req.actor, "reason": req.note or "manual"})
    elif action == "resume":
        L().control(req.actor, "resume", bot_id, None, {"paused": False}, req.note)
        for p in (cdir / f"{bot_id}.pause", cdir / f"{bot_id}.kill"):
            if p.exists():
                p.unlink()
    elif action == "flatten":
        L().control(req.actor, "flatten", bot_id, None, {"flatten": True}, req.note)
        Control.write_flag(cdir / f"{bot_id}.flatten", {"actor": req.actor, "reason": req.note or "manual"})
        _trigger_reconcile(bot_id)
    elif action == "kill":
        L().control(req.actor, "kill", bot_id, None, {"killed": True}, req.note)
        Control.write_flag(cdir / f"{bot_id}.kill", {"actor": req.actor, "reason": req.note or "manual"})
        Control.write_flag(cdir / f"{bot_id}.flatten", {"actor": req.actor, "reason": "kill"})
        _trigger_reconcile(bot_id)
    elif action == "rerun":
        L().control(req.actor, "rerun", bot_id, None, {"cmd": req.note or "check"}, "")
        _run_bot_cmd(bot_id, req.note or "check")
    else:
        raise HTTPException(400, "unknown action")
    L().set_bot_status(bot_id, Control(bot_id).status_word())
    return {"ok": True}


def _run_bot_cmd(bot_id: str, cmd: str) -> None:
    if cmd not in ("check", "reconcile", "decide", "status"):
        raise HTTPException(400, "bad command")
    bots_dir = var_dir().parent / "bots"
    for p in bots_dir.glob("*/bot.py"):
        try:
            txt = p.read_text(errors="ignore")
        except OSError:
            continue
        if f'id="{bot_id}"' in txt or f"id='{bot_id}'" in txt or (p.parent / "cc.py").exists() and f'id="{bot_id}"' in (p.parent / "cc.py").read_text(errors="ignore"):
            subprocess.Popen([sys.executable, str(p), cmd], cwd=str(p.parent))
            return


class LimitReq(BaseModel):
    value: Any
    note: str = ""
    actor: str = "operator"


@router.put("/limits/{scope}/{key}")
def set_limit(scope: str, key: str, req: LimitReq) -> dict[str, Any]:
    allowed = set(PORTFOLIO_DEFAULTS) if scope == "portfolio" else set(DEFAULT_LIMITS)
    if key not in allowed:
        raise HTTPException(400, f"unknown limit {key} for scope {scope}")
    before = L().limit(scope, key, (PORTFOLIO_DEFAULTS if scope == "portfolio" else DEFAULT_LIMITS)[key])
    L().control(req.actor, "limit", f"{scope}.{key}", before, req.value, req.note)  # audit first
    L().set_limit(scope, key, req.value)
    return {"ok": True, "before": before, "after": req.value}
