"""
Command Center integration for spy_mr_bot. Everything the SDK needs lives here so bot.py stays close to the
original and strategy.py is untouched. Importing this module registers the bot manifest.

If cc_sdk is not installed (e.g. bot copied to a machine without the Command Center), every helper degrades
to a no-op EXCEPT risk checks, which then fail closed for new entries. That is deliberate.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any

MODE = os.getenv("MODE", "paper").lower()

try:
    from cc_sdk import Bot, BotManifest, Order

    MANIFEST = BotManifest(
        id="spy_mr",
        name="SPY Daily Mean Reversion",
        version="1.2",
        strategy_line="RSI(2) < 10 above SMA200 · exit SMA5 / 10 bars · 5% stop",
        instrument=os.getenv("SYMBOL", "SPY"),
        mode=MODE,
        cadence={"decide": "15:50", "reconcile": "09:45"},
        backtest={
            "win_rate": 0.77, "profit_factor": 2.28, "avg_win": 0.0121, "avg_loss": -0.0081,
            "trades_per_year": 5, "slippage_assumed": 0.01, "max_dd": 0.116,
        },
        limits={
            "max_position_usd": float(os.getenv("CC_MAX_POSITION_USD", "100000")),
            "max_orders_per_day": 2, "max_bot_dd": 0.12, "max_consecutive_losses": 4,
            "price_collar_pct": 0.015, "stale_quote_s": 90,
        },
    )
    bot: Bot | None = Bot(MANIFEST)
    SDK = True
except Exception:  # noqa: BLE001 - cc_sdk missing or ledger unreachable
    bot = None
    SDK = False
    Order = None  # type: ignore[assignment]


class _NullRun:
    def decision(self, *a: Any, **k: Any) -> None: ...
    def order_sent(self, *a: Any, **k: Any) -> None: ...
    def note(self, *a: Any, **k: Any) -> None: ...


@contextmanager
def run(name: str):
    if bot is None:
        yield _NullRun()
        return
    with bot.run(name) as r:
        yield r


class Rejected(RuntimeError):
    pass


def guarded(run_: Any, *, side: str, qty: int, type_: str, symbol: str, ref_price: float, reduces_risk: bool,
            quote_age_s: float = 0.0, stop_price: float | None = None, send=None) -> str:
    """Run the pre-trade check, then call send() which returns the broker order id. Raises Rejected if blocked."""
    if bot is None:
        if not reduces_risk:
            raise Rejected("cc_sdk unavailable: new entries are blocked (fail closed)")
        return send()
    o = Order(side=side, qty=qty, type=type_, symbol=symbol, ref_price=ref_price, quote_age_s=quote_age_s,
              reduces_risk=reduces_risk, stop_price=stop_price)
    r = bot.risk.pre_trade(o)
    if not r.ok:
        raise Rejected(r.reason)
    oid = send()
    run_.order_sent(o, r, broker_order_id=oid)
    return oid


def flatten_requested() -> bool:
    return bool(bot and bot.control.flatten_requested())


def clear_flatten() -> None:
    if bot:
        bot.control.clear_flatten()


def record_fill(side: str, qty: int, price: float, expected: float, commission: float = 0.0) -> None:
    if bot:
        bot.record_fill(bot.last_sent_order_id(side), qty, price, expected, commission)


def set_position(symbol: str, qty: int, avg_price: float | None, entry_at: str | None, bars_held: int) -> None:
    if bot:
        bot.set_position(symbol, qty, avg_price, entry_at, bars_held)


def record_equity(value: float, source: str) -> None:
    if bot:
        bot.record_equity(value, source)


def record_trade(**kw: Any) -> None:
    if bot:
        bot.record_trade(**kw)
