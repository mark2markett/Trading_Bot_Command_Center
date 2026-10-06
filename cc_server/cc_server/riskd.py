"""
riskd: the server's background loop (every 15 s).
  - portfolio drawdown ladder on BROKER equity -> pause / flatten most-correlated pair / kill
  - heartbeat watchdog -> degraded + page
  - parity recompute per bot
  - Schwab token age from token file mtime (read-only; never reads the token)
  - correlation matrix over 60d daily bot-equity returns
  - page delivery, 06:00 ET digest, early-close notice
Pure functions take (L, now) so tests can drive the clock.
"""
from __future__ import annotations

import logging
import os
import statistics
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from cc_sdk.control import Control, control_dir
from cc_sdk.ledger import Ledger, var_dir
from cc_sdk.manifest import PORTFOLIO_DEFAULTS

from cc_sdk import paper_account

from . import calendar as cal
from . import db, parity
from .alerts import Alerter

ET = ZoneInfo("America/New_York")
log = logging.getLogger("riskd")


def plim(L: Ledger, key: str) -> float:
    return float(L.limit("portfolio", key, PORTFOLIO_DEFAULTS[key]))


# ---------------------------------------------------------------------------
def portfolio_drawdown(L: Ledger) -> dict[str, Any]:
    paper = paper_account.config(L)
    if paper and not paper_account.snapshot(L)["ready"]:
        return {"dd": 0.0, "equity": None, "peak": None, "source": "paper"}
    series = db.broker_equity_series(L, days=400)
    if not series:
        return {"dd": 0.0, "equity": None, "peak": None, "source": "none"}
    vals = [v for _, v in series]
    peak = max(vals); last = vals[-1]
    return {"dd": 0.0 if peak <= 0 else (peak - last) / peak, "equity": last, "peak": peak, "source": "paper" if paper else "broker"}


def day_pnl(L: Ledger) -> dict[str, Any]:
    if paper_account.config(L):
        value = paper_account.snapshot(L)
        return {"pnl": value.get("day_pnl", 0.), "pct": value.get("day_pct", 0.)}
    series = db.broker_equity_series(L, days=5)
    if len(series) < 2:
        return {"pnl": 0.0, "pct": 0.0}
    today = datetime.now(ET).date().isoformat()
    prev = [v for at, v in series if not at.startswith(today)]
    base = prev[-1] if prev else series[0][1]
    last = series[-1][1]
    return {"pnl": last - base, "pct": 0.0 if base == 0 else (last - base) / base}


def gross_exposure(L: Ledger) -> dict[str, Any]:
    eq = L.latest_broker_equity_total()
    paper = paper_account.snapshot(L) if paper_account.config(L) else None
    gross = paper["gross"] if paper and paper["ready"] else L.gross_exposure_usd()
    return {"usd": gross, "ratio": 0.0 if not eq else gross / eq, "cap": plim(L, "max_gross_exposure")}


def correlation(L: Ledger, days: int = 60) -> dict[str, Any]:
    bots = [b["id"] for b in db.bot_rows(L)]
    daily: dict[str, dict[str, float]] = {}
    for b in bots:
        s = db.equity_series(L, b, days=days)
        byday: dict[str, float] = {}
        for at, v in s:
            byday[at[:10]] = v
        days_sorted = sorted(byday)
        rets = {}
        for a, bday in zip(days_sorted, days_sorted[1:], strict=False):
            if byday[a]:
                rets[bday] = byday[bday] / byday[a] - 1
        daily[b] = rets
    ids = [b for b in bots if len(daily[b]) >= 10]
    m: dict[str, dict[str, float]] = {}
    flags: list[str] = []
    for i in ids:
        m[i] = {}
        for j in ids:
            common = sorted(set(daily[i]) & set(daily[j]))
            if i == j:
                m[i][j] = 1.0; continue
            if len(common) < 10:
                m[i][j] = 0.0; continue
            x = [daily[i][d] for d in common]; y = [daily[j][d] for d in common]
            try:
                r = statistics.correlation(x, y)
            except statistics.StatisticsError:
                r = 0.0
            m[i][j] = round(r, 2)
            if i < j and r >= 0.7:
                flags.append(f"{i} and {j} move together ({r:.2f}). Treat them as one risk unit when sizing.")
    return {"ids": ids, "matrix": m, "flags": flags}


def most_correlated_pair(L: Ledger) -> tuple[str, str] | None:
    c = correlation(L)
    best = None
    for i in c["ids"]:
        for j in c["ids"]:
            if i < j and (best is None or c["matrix"][i][j] > best[0]):
                best = (c["matrix"][i][j], i, j)
    return (best[1], best[2]) if best else None


# ---------------------------------------------------------------------------
def apply_ladder(L: Ledger, now: datetime | None = None) -> list[str]:
    """Escalating automatic responses. Each step fires once (tracked in kv) until re-armed."""
    now = now or datetime.now(timezone.utc)
    dd = portfolio_drawdown(L)["dd"]
    cdir = control_dir(); cdir.mkdir(parents=True, exist_ok=True)
    fired = db.kv_get(L, "ladder_fired", {})
    actions: list[str] = []
    steps = [("pause", plim(L, "dd_pause_pct")), ("flatten", plim(L, "dd_flatten_pct")), ("kill", plim(L, "dd_kill_pct"))]
    for name, thr in steps:
        if dd >= thr and not fired.get(name):
            if name == "pause":
                L.control("riskd", "pause_entries", "fleet", {"dd": dd}, {"threshold": thr}, "drawdown ladder")
                Control.write_flag(cdir / "PAUSE_ENTRIES", {"actor": "riskd", "reason": f"portfolio dd {dd:.1%}"})
                L.alert("page", "ladder_pause", f"Portfolio drawdown {dd:.1%} ≥ {thr:.0%}: new entries paused fleet-wide")
            elif name == "flatten":
                pair = most_correlated_pair(L)
                targets = list(pair) if pair else [b["id"] for b in db.bot_rows(L) if db.position(L, b["id"]) and db.position(L, b["id"])["qty"]][:2]
                L.control("riskd", "flatten", ",".join(targets), {"dd": dd}, {"threshold": thr}, "drawdown ladder")
                for t in targets:
                    Control.write_flag(cdir / f"{t}.flatten", {"actor": "riskd", "reason": f"portfolio dd {dd:.1%}"})
                L.alert("page", "ladder_flatten", f"Portfolio drawdown {dd:.1%} ≥ {thr:.0%}: flattening {', '.join(targets) or 'nothing open'}")
            else:
                L.control("riskd", "kill_all", "fleet", {"dd": dd}, {"threshold": thr}, "drawdown ladder")
                Control.write_flag(cdir / "KILL", {"actor": "riskd", "reason": f"portfolio dd {dd:.1%}"})
                for b in db.bot_rows(L):
                    Control.write_flag(cdir / f"{b['id']}.flatten", {"actor": "riskd", "reason": "kill"})
                L.alert("page", "ladder_kill", f"Portfolio drawdown {dd:.1%} ≥ {thr:.0%}: KILL SWITCH FIRED. Manual re-arm required.")
            fired[name] = now.isoformat(); actions.append(name)
    db.kv_set(L, "ladder_fired", fired)
    return actions


def heartbeat_watch(L: Ledger, now: datetime | None = None) -> list[str]:
    """A live or paper bot whose scheduled run has not reported within grace minutes is degraded. Live -> page."""
    now = now or datetime.now(timezone.utc)
    grace = timedelta(minutes=plim(L, "heartbeat_grace_min"))
    now_et = now.astimezone(ET)
    flagged: list[str] = []
    paged = db.kv_get(L, "hb_paged", {})
    for b in db.bot_rows(L):
        if b["status"] in ("killed",):
            continue
        if not cal.is_trading_day(now_et.date()):
            continue
        for run, hhmm in (b.get("cadence") or {}).items():
            hh, mm = map(int, hhmm.split(":"))
            if run == "decide" and cal.is_early_close(now_et.date()):
                hh, mm = 12, 50
            due = now_et.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if now_et < due + grace:
                continue
            if run == "session":
                # intraday runner heartbeats every 5 min while the market is open: a dead session shows up within grace
                close = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
                since = max(due, min(now_et, close) - grace)
            else:
                since = due
            hb = L.one("SELECT at, ok FROM heartbeats WHERE bot_id=? AND run=? AND at>=? ORDER BY id DESC LIMIT 1",
                       (b["id"], run, since.astimezone(timezone.utc).isoformat()))
            key = f"{b['id']}:{run}:{now_et.date()}"
            if hb is None or not hb["ok"]:
                flagged.append(b["id"])
                if not paged.get(key):
                    sev = "page" if b["mode"] == "live" else "digest"
                    what = "missed" if hb is None else "failed"
                    L.alert(sev, "heartbeat", f"{b['name']}: {run} run {what} ({hhmm} ET + {int(grace.total_seconds()//60)} min)", b["id"])
                    paged[key] = now.isoformat()
    db.kv_set(L, "hb_paged", paged)
    return flagged


def token_days_left(bots_dir: Path | None = None) -> dict[str, Any]:
    """Schwab refresh tokens die after 7 days. Issue time comes from the SDK's `.issued` sidecar (no secret in it);
    since the broker design (M6.8) there is normally NO token file on this machine, only the sidecar. A legacy
    token file without a sidecar falls back to its mtime; its contents are never read."""
    bots_dir = bots_dir or (var_dir().parent / "bots")
    newest = None
    for p in [var_dir() / "schwab_token.json", *bots_dir.glob("*/schwab_token.json")]:
        side = Path(str(p) + ".issued")   # written by the SDK: issue time only, no secret
        if not p.exists() and not side.exists():
            continue
        try:
            import json

            m = datetime.fromtimestamp(int(json.loads(side.read_text())["creation_timestamp"]), tz=timezone.utc) if side.exists() \
                else datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
        except Exception:  # noqa: BLE001
            if not p.exists():
                continue   # corrupt sidecar and no legacy token file: nothing trustworthy to date it from
            m = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
        newest = m if newest is None or m > newest else newest
    if newest is None:
        return {"present": False, "days_left": None}
    left = 7 - (datetime.now(timezone.utc) - newest).total_seconds() / 86400
    return {"present": True, "days_left": round(left, 1), "refreshed_at": newest.isoformat()}


def token_watch(L: Ledger) -> None:
    t = token_days_left()
    if t.get("present") and t["days_left"] is not None and t["days_left"] < 2:
        key = f"token:{datetime.now(ET).date()}"
        if not db.kv_get(L, key):
            L.alert("page", "token", f"Schwab token expires in {t['days_left']:.1f} days. Run `python bot.py auth`.")
            db.kv_set(L, key, True)


def early_close_notice(L: Ledger) -> None:
    today = datetime.now(ET).date()
    nxt = cal.next_early_close(today)
    if nxt and (nxt - today).days == 1:
        key = f"early:{nxt}"
        if not db.kv_get(L, key):
            L.alert("digest", "calendar", f"Early close {nxt:%a %m/%d} (1:00 pm). Daily bots: decide run moves to 12:50 pm.")
            db.kv_set(L, key, True)


def parity_all(L: Ledger) -> dict[str, dict[str, Any]]:
    out = {}
    for b in db.bot_rows(L):
        out[b["id"]] = parity.evaluate(b.get("backtest") or {}, db.trades(L, b["id"]), db.fills(L, b["id"], 200))
        prev = db.kv_get(L, f"parity:{b['id']}")
        if out[b["id"]]["verdict"] == "drift" and prev != "drift":
            L.alert("page" if b["mode"] == "live" else "digest", "parity",
                    f"{b['name']}: live results drifting from backtest — {out[b['id']]['sentence']}", b["id"])
        db.kv_set(L, f"parity:{b['id']}", out[b["id"]]["verdict"])
    return out


def bot_status(L: Ledger, b: dict[str, Any], flagged_hb: list[str], par: dict[str, Any]) -> str:
    c = Control(b["id"])
    if c.killed():
        return "killed"
    pos = db.position(L, b["id"])
    degraded = b["id"] in flagged_hb or par.get("verdict") == "drift" or db.rejected_orders_24h(L, b["id"]) > 0
    if degraded:
        return "degraded"
    if c.entries_paused() and not (pos and pos["qty"]):
        return "paused"
    return "running"


_paper_feed = None


def paper_feed():
    global _paper_feed
    if _paper_feed is None:
        from cc_sdk.schwab_feed import SchwabFeed
        _paper_feed = SchwabFeed.connect(Path(__file__).resolve().parents[2] / "bots" / "spy_mr_bot")
    return _paper_feed


def refresh_paper_account(L: Ledger) -> dict | None:
    if not paper_account.config(L):
        return None
    for row in L.q("SELECT DISTINCT symbol FROM positions WHERE qty != 0"):
        try:
            price, age = paper_feed().account_quote(row["symbol"])
            if not 0 <= age <= 90:
                raise ValueError("Quote is stale")
            paper_account.mark(L,row["symbol"],price,datetime.now(timezone.utc)-timedelta(seconds=age))
        except Exception as error:
            # Preserve previous quote's timestamp: a failed refresh cannot manufacture a fresh mark.
            log.warning("paper mark refresh failed: symbol=%s error=%s",row["symbol"],type(error).__name__)
    return paper_account.record(L)


def tick(L: Ledger, alerter: Alerter | None = None) -> dict[str, Any]:
    """One riskd pass. Returns a summary for /api/health."""
    account = refresh_paper_account(L)
    actions = apply_ladder(L)
    flagged = heartbeat_watch(L)
    token_watch(L)
    early_close_notice(L)
    par = parity_all(L)
    for b in db.bot_rows(L):
        L.set_bot_status(b["id"], bot_status(L, b, flagged, par.get(b["id"], {})))
    delivered = 0
    if alerter:
        delivered = alerter.deliver_pending_pages()
        now_et = datetime.now(ET)
        if now_et.hour == int(alerter.cfg.get("digest", {}).get("hour_et", 6)) and not db.kv_get(L, f"digest:{now_et.date()}"):
            alerter.send_digest(); db.kv_set(L, f"digest:{now_et.date()}", True)
    summary = {"at": datetime.now(timezone.utc).isoformat(), "ladder_actions": actions, "degraded": flagged, "pages_delivered": delivered, "paper_account": account}
    db.kv_set(L, "riskd_last", summary)
    return summary


def rearm(L: Ledger, actor: str, note: str) -> None:
    cdir = control_dir()
    L.control(actor, "rearm", "fleet", {"killed": (cdir / "KILL").exists()}, {"killed": False}, note)
    for p in [cdir / "KILL", cdir / "PAUSE_ENTRIES"] + list(cdir.glob("*.kill")):
        if p.exists():
            p.unlink()
    db.kv_set(L, "ladder_fired", {})


def today_is_trading(d: date | None = None) -> bool:
    return cal.is_trading_day(d or datetime.now(ET).date())


def host_info() -> dict[str, Any]:
    import shutil
    total, used, free = shutil.disk_usage(str(var_dir().parent))
    return {"disk_free_gb": round(free / 1e9, 1), "pid": os.getpid()}
