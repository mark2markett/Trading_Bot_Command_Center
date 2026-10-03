"""
Template bot: the smallest bot that fully participates in the Command Center.
Run:  python bot.py decide | reconcile | status
It trades nothing real. Replace `signal()` and the broker calls with your own.
"""
import json
import sys

from cc_sdk import Bot, BotManifest, Order

MANIFEST = BotManifest(
    id="template", name="Template Bot", version="0.1",
    strategy_line="buys when the coin says so · exits next day",
    instrument="SPY", mode="paper",
    cadence={"decide": "15:50", "reconcile": "09:45"},
    backtest={"win_rate": 0.5, "profit_factor": 1.0, "avg_win": 0.01, "avg_loss": -0.01,
              "trades_per_year": 50, "slippage_assumed": 0.01, "max_dd": 0.10},
    limits={"max_position_usd": 10_000, "max_orders_per_day": 2},
)
bot = Bot(MANIFEST)
PRICE = 500.0  # stand-in for a quote


def signal() -> dict:
    return {"price": PRICE, "coin": "heads"}


def decide() -> None:
    with bot.run("decide") as run:
        s = signal()
        if bot.control.flatten_requested():
            run.decision(s, "SELL_MOC", "flatten requested")
            o = Order(side="SELL", qty=10, type="MOC", symbol="SPY", ref_price=PRICE, reduces_risk=True)
            r = bot.risk.pre_trade(o)
            run.order_sent(o, r, broker_order_id="paper")
            bot.record_fill(bot.last_sent_order_id("SELL"), 10, PRICE, PRICE)
            bot.set_position("SPY", 0)
            bot.control.clear_flatten()
            return
        if s["coin"] == "heads":
            o = Order(side="BUY", qty=10, type="MOC", symbol="SPY", ref_price=PRICE, quote_age_s=0.5)
            r = bot.risk.pre_trade(o)
            if r.ok:
                oid = "paper-" + bot.now
                run.decision(s, "BUY_MOC", "coin heads")
                run.order_sent(o, r, broker_order_id=oid)
                # paper fill at ref price
                bot.record_fill(bot.last_sent_order_id("BUY"), 10, PRICE + 0.01, PRICE, 0.035)
                bot.set_position("SPY", 10, PRICE + 0.01, bot.now, 0)
            else:
                run.decision(s, "NONE", f"rejected: {r.reason}")
        else:
            run.decision(s, "NONE", "coin tails")
        bot.record_equity(10_000.0, source="bot")


def reconcile() -> None:
    with bot.run("reconcile") as run:
        pos = bot.L.one("SELECT qty FROM positions WHERE bot_id=?", (MANIFEST.id,))
        run.decision({"position": dict(pos) if pos else None}, "NONE", "reconcile ok")
        bot.record_equity(10_000.0, source="bot")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "decide":
        decide()
    elif cmd == "reconcile":
        reconcile()
    else:
        print(json.dumps({"status": bot.control.status_word(),
                          "position": [dict(r) for r in bot.L.q("SELECT * FROM positions WHERE bot_id=?", (MANIFEST.id,))]},
                         indent=2, default=str))
