import json
from pathlib import Path

import pytest

from cc_sdk import Bot, BotManifest, Order


def mk(tmp_path: Path, mode="paper", **limits):
    cdir = tmp_path / "control"
    cdir.mkdir()
    m = BotManifest(id="t_bot", name="Template", version="0.1", strategy_line="x", instrument="SPY", mode=mode,
                    cadence={"decide": "15:50"}, limits=limits)
    bot = Bot(m, db_path=tmp_path / "cc.db", control_dir=cdir)
    bot.record_equity(100_000, source="broker")  # explicit synthetic account equity
    return bot, cdir


def entry(qty=100, px=500.0, age=1.0, **kw):
    return Order(side="BUY", qty=qty, type="MOC", symbol="SPY", ref_price=px, quote_age_s=age, **kw)


def test_kill_blocks_entry_allows_stop(tmp_path):
    bot, cdir = mk(tmp_path)
    (cdir / "KILL").write_text("{}")
    r = bot.risk.pre_trade(entry())
    assert not r.ok and r.reason.startswith("kill")
    s = bot.risk.pre_trade(Order(side="SELL", qty=100, type="STOP", symbol="SPY", ref_price=500, reduces_risk=True))
    assert s.ok
    row = bot.L.one("SELECT status, reason FROM orders")
    assert row["status"] == "rejected"


def test_missing_control_dir_fails_closed(tmp_path):
    m = BotManifest(id="t_bot", name="T", version="0", strategy_line="x", instrument="SPY", mode="paper")
    bot = Bot(m, db_path=tmp_path / "cc.db", control_dir=tmp_path / "nope")
    assert not bot.risk.pre_trade(entry()).ok
    assert bot.risk.pre_trade(Order(side="SELL", qty=1, type="MKT", symbol="SPY", ref_price=1, reduces_risk=True)).ok


def test_pause_blocks_entry_allows_exit(tmp_path):
    bot, cdir = mk(tmp_path)
    (cdir / "PAUSE_ENTRIES").write_text("{}")
    assert not bot.risk.pre_trade(entry()).ok
    assert bot.risk.pre_trade(Order(side="SELL", qty=5, type="MOC", symbol="SPY", ref_price=500, reduces_risk=True)).ok


def test_fat_finger_rejected_with_alert_severity(tmp_path):
    bot, _ = mk(tmp_path, mode="live", max_order_usd=10_000)
    r = bot.risk.pre_trade(entry(qty=100, px=500))  # $50k
    assert not r.ok and "max_order_usd" in r.reason
    a = bot.L.one("SELECT severity, kind FROM alerts")
    assert a["severity"] == "page" and a["kind"] == "order_rejected"
    (tmp_path / "p").mkdir()
    bot2, _ = mk(tmp_path / "p", mode="paper", max_order_usd=10_000)
    bot2.risk.pre_trade(entry(qty=100, px=500))
    assert bot2.L.one("SELECT severity FROM alerts")["severity"] == "digest"


def test_stale_quote_rejected(tmp_path):
    bot, _ = mk(tmp_path, stale_quote_s=90)
    assert not bot.risk.pre_trade(entry(age=120)).ok


def test_duplicate_and_orders_per_day(tmp_path):
    bot, _ = mk(tmp_path, max_orders_per_day=2)
    with bot.run("decide") as run:
        o = entry(qty=10)
        r = bot.risk.pre_trade(o)
        assert r.ok
        run.order_sent(o, r, "b1")
    assert not bot.risk.pre_trade(entry(qty=10)).ok  # duplicate BUY same day
    with bot.run("decide") as run:
        o = Order(side="SELL_SHORT", qty=10, type="MOC", symbol="SPY", ref_price=500)
        r = bot.risk.pre_trade(o)
        assert r.ok
        run.order_sent(o, r, "b2")
    r = bot.risk.pre_trade(Order(side="BUY_TO_COVER", qty=1, type="MOC", symbol="SPY", ref_price=500))
    assert not r.ok and "max_orders_per_day" in r.reason


def test_consecutive_losses_auto_pause(tmp_path):
    bot, cdir = mk(tmp_path, max_consecutive_losses=4)
    for i in range(4):
        bot.record_trade(entry_at=f"2026-01-0{i+1}", exit_at=f"2026-01-0{i+2}", qty=1, entry_px=1, exit_px=0.9,
                         bars=1, exit_reason="x", pnl=-1.0, slippage=0)
    r = bot.risk.pre_trade(entry(qty=1))
    assert not r.ok and "consecutive" in r.reason
    assert (cdir / "t_bot.pause").exists()
    assert bot.L.one("SELECT kind FROM alerts WHERE kind='auto_pause'")


def test_bot_drawdown_auto_pause(tmp_path):
    bot, cdir = mk(tmp_path, max_bot_dd=0.10)
    bot.record_equity(100_000); bot.record_equity(88_000)
    r = bot.risk.pre_trade(entry(qty=1))
    assert not r.ok and "max_bot_dd" in r.reason and (cdir / "t_bot.pause").exists()


def test_gross_exposure_cap(tmp_path):
    bot, _ = mk(tmp_path, max_order_usd=10_000_000, max_position_usd=10_000_000, max_order_qty=100_000)
    bot.record_equity(100_000, source="broker")
    bot.L.set_position("other", "QQQ", 200, 600, None, 0)  # $120k already
    r = bot.risk.pre_trade(entry(qty=100, px=500))  # +$50k -> 1.7x > 1.5x
    assert not r.ok and "max_gross_exposure" in r.reason


def test_heartbeat_on_success_and_failure(tmp_path):
    bot, _ = mk(tmp_path)
    with bot.run("reconcile"):
        pass
    with pytest.raises(ZeroDivisionError):
        with bot.run("decide"):
            1 / 0
    rows = bot.L.q("SELECT run, ok, detail FROM heartbeats ORDER BY id")
    assert [(r["run"], r["ok"]) for r in rows] == [("reconcile", 1), ("decide", 0)]
    assert "ZeroDivisionError" in rows[1]["detail"]
    assert bot.L.one("SELECT kind FROM alerts WHERE kind='run_failed'")


def test_manifest_validation():
    with pytest.raises(ValueError):
        BotManifest(id="Bad Id", name="x", version="1", strategy_line="", instrument="SPY", mode="paper")
    m = BotManifest(id="ok_id", name="x", version="1", strategy_line="", instrument="SPY", mode="paper",
                    limits={"max_orders_per_day": 5})
    assert m.limits["max_orders_per_day"] == 5 and m.limits["stale_quote_s"] == 90
    assert json.dumps(m.to_row())


def test_multi_symbol_positions_and_per_symbol_duplicate(tmp_path):
    bot, _ = mk(tmp_path, max_orders_per_day=40, max_position_usd=10_000_000, max_order_usd=10_000_000, max_order_qty=100_000)
    bot.set_position("AAA", 100, 10.0, "2026-01-01", 0, stop_price=9.5)
    bot.set_position("BBB", -50, 20.0, "2026-01-01", 0, stop_price=21.0)
    ps = bot.positions()
    assert [(p["symbol"], p["qty"], p["side"]) for p in ps] == [("AAA", 100, "LONG"), ("BBB", -50, "SHORT")]
    bot.set_position("AAA", 0)
    assert [p["symbol"] for p in bot.positions()] == ["BBB"]
    with bot.run("session") as run:
        o = Order(side="BUY", qty=10, type="STOP", symbol="AAA", ref_price=10, stop_price=10.2)
        r = bot.risk.pre_trade(o); assert r.ok; run.order_sent(o, r, "x1")
        o2 = Order(side="BUY", qty=10, type="STOP", symbol="CCC", ref_price=10, stop_price=10.2)
        assert bot.risk.pre_trade(o2).ok  # same side, different symbol: allowed
        assert not bot.risk.pre_trade(Order(side="BUY", qty=10, type="STOP", symbol="AAA", ref_price=10)).ok  # dup


def test_old_single_key_positions_table_migrates(tmp_path):
    import sqlite3
    db = tmp_path / "old.db"
    c = sqlite3.connect(db)
    c.executescript("CREATE TABLE positions(bot_id TEXT PRIMARY KEY, symbol TEXT, qty INTEGER, avg_price REAL, entry_at TEXT, bars_held INTEGER, updated_at TEXT);"
                    "INSERT INTO positions VALUES('spy_mr','SPY',153,651.2,'2026-09-15',2,'2026-09-17');")
    c.commit(); c.close()
    from cc_sdk.ledger import Ledger
    L = Ledger(db)
    rows = L.positions_for("spy_mr")
    assert len(rows) == 1 and rows[0]["symbol"] == "SPY" and rows[0]["qty"] == 153
    L.set_position("spy_mr", "QQQ", 10, 600, None, 0)
    assert [r["symbol"] for r in L.positions_for("spy_mr")] == ["QQQ", "SPY"]
