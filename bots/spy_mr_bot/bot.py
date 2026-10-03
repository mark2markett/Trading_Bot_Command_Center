"""
SPY Daily Mean Reversion bot.

Two scheduled runs per trading day (Windows Task Scheduler, see install_tasks.ps1):

  decide     3:50 pm ET  - compute today's signal using the live price as the provisional close,
                           queue a market-on-close BUY or SELL if the rules say so.
  reconcile  9:45 am ET  - confirm yesterday's fill, place/refresh the 5% protective stop,
                           update bars-held, log the state.

Other commands:  status | auth | check

MODE=paper  (default)  nothing is sent to Schwab; fills are simulated at the real close.
MODE=live              real orders. Requires LIVE_CONFIRM=I_UNDERSTAND_THIS_IS_REAL_MONEY in .env.
"""
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

import cc
import strategy as S
from broker import BrokerError, PaperBroker, SchwabBroker

HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env")

ET = ZoneInfo("America/New_York")
SYMBOL = os.getenv("SYMBOL", "SPY")
MODE = os.getenv("MODE", "paper").lower()
ALLOC_PCT = float(os.getenv("ALLOCATION_PCT", "100"))
MAX_SHARES = int(os.getenv("MAX_SHARES", "0"))  # 0 = no cap
STATE_PATH = HERE / f"state_{MODE}.json"
LOG_PATH = HERE / "bot.log"
P = S.Params(stop_pct=float(os.getenv("STOP_PCT", "5")))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    handlers=[logging.FileHandler(LOG_PATH), logging.StreamHandler(sys.stdout)])
log = logging.getLogger("bot")


# ---------------------------------------------------------------------------
def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {"in_position": False, "qty": 0, "entry_price": None, "entry_date": None,
            "bars_held": 0, "pending": None, "stop_order_id": None, "last_decide": None, "last_reconcile": None}


def save_state(st: dict):
    STATE_PATH.write_text(json.dumps(st, indent=2))


def make_broker():
    creds_ok = all(os.getenv(k) for k in ("SCHWAB_API_KEY", "SCHWAB_APP_SECRET", "SCHWAB_CALLBACK_URL"))
    if MODE == "live":
        if os.getenv("LIVE_CONFIRM") != "I_UNDERSTAND_THIS_IS_REAL_MONEY":
            raise SystemExit("MODE=live but LIVE_CONFIRM is not set. Refusing to run.")
        if not creds_ok:
            raise SystemExit("MODE=live needs SCHWAB_API_KEY, SCHWAB_APP_SECRET, SCHWAB_CALLBACK_URL")
        return SchwabBroker(os.environ["SCHWAB_API_KEY"], os.environ["SCHWAB_APP_SECRET"],
                            os.environ["SCHWAB_CALLBACK_URL"], str(HERE / os.getenv("TOKEN_PATH", "schwab_token.json")),
                            int(os.getenv("ACCOUNT_INDEX", "0")))
    data = None
    if creds_ok and os.getenv("PAPER_USE_SCHWAB_DATA", "true").lower() == "true":
        try:
            data = SchwabBroker(os.environ["SCHWAB_API_KEY"], os.environ["SCHWAB_APP_SECRET"],
                                os.environ["SCHWAB_CALLBACK_URL"], str(HERE / os.getenv("TOKEN_PATH", "schwab_token.json")))
            log.info("paper mode: using Schwab market data, no orders will be sent")
        except Exception as e:  # noqa: BLE001
            log.warning("Schwab data unavailable (%s); falling back to Stooq end-of-day data", e)
    return PaperBroker(str(HERE / "paper_ledger.json"), float(os.getenv("PAPER_CASH", "100000")), data=data)


def trading_day_today() -> bool:
    now = datetime.now(ET)
    return now.weekday() < 5  # holidays: Schwab/Stooq simply return no new bar; reconcile handles that


# ---------------------------------------------------------------------------
def cmd_decide(b, st, run=cc._NullRun()):
    """3:50 pm ET. Decide and queue a MOC order."""
    if not trading_day_today():
        log.info("weekend, nothing to do"); return
    bars = b.daily_closes(SYMBOL, 260)
    closes = [x["close"] for x in bars]
    today = datetime.now(ET).date().isoformat()
    live = b.last_price(SYMBOL)
    # Use the live price as today's provisional close. If the feed already has today's bar, replace it.
    if bars[-1]["date"] == today:
        closes[-1] = live
    else:
        closes.append(live)
    snap = S.snapshot(closes, P)
    log.info("decide %s price=%.2f rsi2=%s sma200=%s sma5=%s in_pos=%s bars_held=%d",
             today, live, _f(snap.rsi), _f(snap.sma_trend), _f(snap.sma_exit), st["in_position"], st["bars_held"])
    signal = {"price": live, "rsi2": _f(snap.rsi), "sma200": _f(snap.sma_trend), "sma5": _f(snap.sma_exit),
              "in_position": st["in_position"], "bars_held": st["bars_held"]}

    broker_qty = b.position(SYMBOL)
    if st["in_position"] and broker_qty <= 0:
        log.warning("state says in position but broker shows %d shares; stop may have fired. Resetting.", broker_qty)
        _flat(st)
    if not st["in_position"] and broker_qty > 0:
        log.warning("broker shows %d shares but state is flat. Adopting broker position.", broker_qty)
        st.update(in_position=True, qty=broker_qty, entry_price=live, entry_date=today, bars_held=0)

    if st["in_position"]:
        reason = S.exit_signal(snap, st["bars_held"] + 1, P)  # +1: today's bar counts once it closes
        if cc.flatten_requested() and not reason:
            reason = "flatten"
        if reason:
            b.cancel_open_orders(SYMBOL)
            oid = cc.guarded(run, side="SELL", qty=st["qty"], type_="MOC", symbol=SYMBOL, ref_price=live,
                             reduces_risk=True, send=lambda: b.sell_moc(SYMBOL, st["qty"]))
            st["pending"] = {"side": "SELL", "qty": st["qty"], "date": today, "reason": reason, "order_id": oid}
            run.decision(signal, "SELL_MOC", reason)
            log.info("SELL MOC %d %s queued (%s) order=%s", st["qty"], SYMBOL, reason, oid)
        else:
            run.decision(signal, "HOLD", "no exit signal")
            log.info("hold; no exit signal")
    else:
        if cc.flatten_requested():
            cc.clear_flatten()
        if S.entry_signal(snap, P):
            eq = b.equity()
            qty = int(eq * ALLOC_PCT / 100.0 // live)
            if MAX_SHARES:
                qty = min(qty, MAX_SHARES)
            if qty <= 0:
                log.warning("entry signal but qty computes to 0 (equity %.2f)", eq); return
            try:
                oid = cc.guarded(run, side="BUY", qty=qty, type_="MOC", symbol=SYMBOL, ref_price=live,
                                 reduces_risk=False, send=lambda: b.buy_moc(SYMBOL, qty))
            except cc.Rejected as e:
                run.decision(signal, "NONE", f"entry rejected: {e}")
                log.warning("entry signal but order rejected by risk engine: %s", e)
                st["last_decide"] = today; save_state(st); return
            st["pending"] = {"side": "BUY", "qty": qty, "date": today, "reason": "rsi2_entry", "order_id": oid}
            run.decision(signal, "BUY_MOC", "rsi2_entry")
            log.info("BUY MOC %d %s queued, provisional price %.2f, order=%s", qty, SYMBOL, live, oid)
        else:
            run.decision(signal, "NONE", "no entry signal")
            log.info("flat; no entry signal")
    st["last_decide"] = today
    save_state(st)


def cmd_reconcile(b, st, run=cc._NullRun()):
    """9:45 am ET next day. Confirm fills, place stop, advance bars_held."""
    bars = b.daily_closes(SYMBOL, 5)
    last = bars[-1]
    if isinstance(b, PaperBroker) and (st["pending"] or b.ledger["stops"]):
        for f in b.settle_pending(last):
            log.info("paper fill: %s", f)

    pend = st.get("pending")
    if pend:
        if pend["date"] > last["date"]:
            log.info("no new bar yet for pending order dated %s; try again later", pend["date"]); return
        qty = b.position(SYMBOL)
        if pend["side"] == "BUY":
            if qty > 0:
                st.update(in_position=True, qty=qty, entry_price=last["close"], entry_date=last["date"], bars_held=0)
                cc.record_fill("BUY", qty, last["close"], last["close"])
                log.info("BUY confirmed: %d @ ~%.2f on %s", qty, last["close"], last["date"])
            else:
                log.warning("BUY did not fill (broker qty=0)")
        else:
            if qty == 0:
                cc.record_fill("SELL", pend["qty"], last["close"], last["close"])
                if st.get("entry_price"):
                    cc.record_trade(entry_at=st["entry_date"], exit_at=last["date"], qty=pend["qty"],
                                    entry_px=st["entry_price"], exit_px=last["close"], bars=st["bars_held"] + 1,
                                    exit_reason=pend["reason"], pnl=(last["close"] - st["entry_price"]) * pend["qty"],
                                    slippage=0.0)
                if pend["reason"] == "flatten":
                    cc.clear_flatten()
                log.info("SELL confirmed on %s (%s)", last["date"], pend["reason"]); _flat(st)
            else:
                log.warning("SELL did not fully fill; broker qty=%d", qty)
        st["pending"] = None
    elif st["in_position"]:
        if b.position(SYMBOL) <= 0:
            if st.get("entry_price"):
                stop_px = S.stop_price(st["entry_price"], P) or last["close"]
                cc.record_trade(entry_at=st["entry_date"], exit_at=last["date"], qty=st["qty"], entry_px=st["entry_price"],
                                exit_px=stop_px, bars=st["bars_held"] + 1, exit_reason="crash_stop",
                                pnl=(stop_px - st["entry_price"]) * st["qty"], slippage=0.0)
            log.info("position gone without a pending sell: protective stop fired"); _flat(st)
        elif last["date"] != st.get("last_reconcile_bar"):
            st["bars_held"] += 1

    if st["in_position"] and P.stop_pct > 0:
        stop = S.stop_price(st["entry_price"], P)
        if not st.get("stop_order_id"):
            b.cancel_open_orders(SYMBOL)
            st["stop_order_id"] = cc.guarded(run, side="SELL", qty=st["qty"], type_="STOP", symbol=SYMBOL,
                                             ref_price=last["close"], reduces_risk=True, stop_price=stop,
                                             send=lambda: b.place_stop(SYMBOL, st["qty"], stop))
            log.info("protective stop placed at %.2f order=%s", stop, st["stop_order_id"])
    if not st["in_position"]:
        st["stop_order_id"] = None

    st["last_reconcile"] = datetime.now(ET).isoformat()
    st["last_reconcile_bar"] = last["date"]
    save_state(st)
    cc.set_position(SYMBOL, st["qty"] if st["in_position"] else 0, st.get("entry_price"), st.get("entry_date"), st["bars_held"])
    cc.record_equity(b.equity(), "broker" if MODE == "live" else "bot")
    run.decision({"last_bar": last["date"], "close": last["close"]}, "RECONCILE", "ok")
    log.info("reconcile ok: last_bar=%s close=%.2f in_pos=%s qty=%d bars_held=%d pending=%s equity=%.2f",
             last["date"], last["close"], st["in_position"], st["qty"], st["bars_held"],
             bool(st["pending"]), b.equity())


def cmd_status(b, st):
    print(json.dumps({"mode": MODE, "symbol": SYMBOL, "equity": round(b.equity(), 2),
                      "broker_position": b.position(SYMBOL), **st}, indent=2))


def cmd_check(b, st):
    """Dry run: print the signal right now without queuing anything."""
    bars = b.daily_closes(SYMBOL, 260)
    closes = [x["close"] for x in bars] + [b.last_price(SYMBOL)]
    snap = S.snapshot(closes, P)
    print(json.dumps({"price": snap.close, "rsi2": snap.rsi, "sma200": snap.sma_trend, "sma5": snap.sma_exit,
                      "entry_signal": S.entry_signal(snap, P),
                      "exit_signal": S.exit_signal(snap, st["bars_held"] + 1, P) if st["in_position"] else None,
                      "bars_in_feed": len(bars), "last_bar": bars[-1]["date"]}, indent=2))


def _flat(st):
    st.update(in_position=False, qty=0, entry_price=None, entry_date=None, bars_held=0, stop_order_id=None)


def _f(x):
    return None if x is None else round(x, 2)


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "auth":
        make_broker() if MODE == "live" else SchwabBroker(
            os.environ["SCHWAB_API_KEY"], os.environ["SCHWAB_APP_SECRET"], os.environ["SCHWAB_CALLBACK_URL"],
            str(HERE / os.getenv("TOKEN_PATH", "schwab_token.json")))
        print("Schwab token saved."); sys.exit(0)
    try:
        broker = make_broker()
        state = load_state()
        if cmd in ("decide", "reconcile"):
            with cc.run(cmd) as run:
                {"decide": cmd_decide, "reconcile": cmd_reconcile}[cmd](broker, state, run)
        else:
            {"status": cmd_status, "check": cmd_check}[cmd](broker, state)
    except (BrokerError, KeyError) as e:
        log.error("run failed: %s", e); sys.exit(1)
