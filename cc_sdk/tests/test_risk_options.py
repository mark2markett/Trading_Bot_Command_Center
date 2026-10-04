"""M7.2 — options in the risk engine. Written before the implementation (CLAUDE.md: tests first for risk.py).

Equity behaviour must be unchanged: every case in test_risk.py still passes untouched. These cases add:
- the x100 contract multiplier in every notional check, applied even if a caller forgets to pass it;
- a per-bot cap on the total debit of one options entry (max_premium_usd);
- spreads are approved only if EVERY leg passes; one bad leg rejects the whole spread;
- closing a spread is risk-reducing: it passes under KILL and PAUSE;
- gross exposure counts option positions at x100.
"""
from pathlib import Path

from cc_sdk import Bot, BotManifest, Order
from cc_sdk.manifest import DEFAULT_LIMITS

CALL_LO = "SPY   261009C00570000"
CALL_HI = "SPY   261009C00575000"


def mk(tmp_path: Path, **limits):
    cdir = tmp_path / "control"
    cdir.mkdir()
    m = BotManifest(id="o_bot", name="Options", version="0.1", strategy_line="x", instrument="SPY options", mode="paper",
                    cadence={"session": "09:25"}, limits=limits)
    return Bot(m, db_path=tmp_path / "cc.db", control_dir=cdir), cdir


def leg(symbol=CALL_LO, side="BUY_TO_OPEN", qty=10, px=3.10, age=1.0, **kw):
    return Order(side=side, qty=qty, type="LMT", symbol=symbol, ref_price=px, quote_age_s=age, multiplier=100, **kw)


def spread(qty=10, lo=3.10, hi=1.05, **kw):
    return [leg(CALL_LO, "BUY_TO_OPEN", qty, lo, **kw), leg(CALL_HI, "SELL_TO_OPEN", qty, hi, **kw)]


def test_default_premium_cap_exists():
    assert DEFAULT_LIMITS["max_premium_usd"] == 5_000


def test_multiplier_applies_to_option_notional(tmp_path):
    bot, _ = mk(tmp_path, max_order_usd=3_000)
    r = bot.risk.pre_trade(leg(qty=10, px=3.10))           # 10 x 3.10 x 100 = $3,100
    assert not r.ok and "max_order_usd" in r.reason and "$3,100" in r.reason
    assert bot.risk.pre_trade(leg(qty=9, px=3.10)).ok       # $2,790


def test_multiplier_enforced_even_if_caller_forgets(tmp_path):
    bot, _ = mk(tmp_path, max_order_usd=3_000)
    forgot = Order(side="BUY_TO_OPEN", qty=10, type="LMT", symbol=CALL_LO, ref_price=3.10, quote_age_s=1.0)  # multiplier left at 1
    r = bot.risk.pre_trade(forgot)
    assert not r.ok and "max_order_usd" in r.reason


def test_equity_notional_unchanged(tmp_path):
    bot, _ = mk(tmp_path, max_order_usd=10_000)
    shares = Order(side="BUY", qty=19, type="MKT", symbol="SPY", ref_price=500.0, quote_age_s=1.0)
    assert bot.risk.pre_trade(shares).ok                    # $9,500, no multiplier for shares


def test_spread_premium_cap(tmp_path):
    bot, _ = mk(tmp_path, max_premium_usd=2_000, max_orders_per_day=8)
    r = bot.risk.pre_trade_spread(spread(qty=10), net_debit=2.05)   # 10 x 2.05 x 100 = $2,050
    assert not r.ok and "max_premium_usd" in r.reason
    statuses = [row["status"] for row in bot.L.q("SELECT status FROM orders ORDER BY id")]
    assert statuses == ["rejected", "rejected"]             # both legs recorded as rejected; nothing sent
    assert bot.risk.pre_trade_spread(spread(qty=9), net_debit=2.05).ok   # $1,845


def test_one_bad_leg_rejects_whole_spread(tmp_path):
    bot, _ = mk(tmp_path, stale_quote_s=90, max_orders_per_day=8)
    legs = [leg(CALL_LO, "BUY_TO_OPEN", 5, 3.10, age=1.0), leg(CALL_HI, "SELL_TO_OPEN", 5, 1.05, age=300.0)]
    r = bot.risk.pre_trade_spread(legs, net_debit=2.05)
    assert not r.ok and "stale_quote" in r.reason
    rows = bot.L.q("SELECT symbol, status, reason FROM orders ORDER BY id")
    assert {row["symbol"] for row in rows} == {CALL_LO, CALL_HI}
    assert all(row["status"] == "rejected" for row in rows)
    assert any("spread rejected" in row["reason"] for row in rows if row["symbol"] == CALL_LO)


def test_spread_needs_a_positive_debit(tmp_path):
    bot, _ = mk(tmp_path, max_orders_per_day=8)
    assert not bot.risk.pre_trade_spread(spread(), net_debit=0.0).ok
    assert not bot.risk.pre_trade_spread([], net_debit=1.0).ok


def test_closing_spread_passes_under_kill_and_pause(tmp_path):
    bot, cdir = mk(tmp_path)
    (cdir / "KILL").write_text("{}")
    (cdir / "PAUSE_ENTRIES").write_text("{}")
    assert not bot.risk.pre_trade_spread(spread(qty=1), net_debit=2.05).ok          # new entry blocked
    close = [leg(CALL_LO, "SELL_TO_CLOSE", 1, 2.50, reduces_risk=True),
             leg(CALL_HI, "BUY_TO_CLOSE", 1, 0.40, reduces_risk=True)]
    assert bot.risk.pre_trade_spread(close, net_debit=0.0).ok                         # closing always allowed


def test_gross_exposure_counts_options_at_x100(tmp_path):
    bot, _ = mk(tmp_path)
    bot.set_position(CALL_LO, 10, 3.00)          # 10 contracts at $3.00/share = $3,000
    bot.set_position("SPY", 5, 500.0)            # 5 shares at $500 = $2,500
    assert bot.L.gross_exposure_usd() == 5_500.0
