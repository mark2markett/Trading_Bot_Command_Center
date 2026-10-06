from datetime import timedelta

import pytest
from cc_sdk import Bot, BotManifest, Order
from cc_sdk.ledger import now


def fleet(tmp_path):
    (tmp_path / "control").mkdir()
    bots = [
        Bot(
            BotManifest(id=name, name=name, version="1", strategy_line="x", instrument="SPY", mode="paper"),
            db_path=tmp_path / "cc.db",
            control_dir=tmp_path / "control",
        )
        for name in ("bot_a", "bot_b")
    ]
    return bots


def test_shared_capital_is_counted_once_and_marks_long_short_options(tmp_path):
    from cc_sdk.paper_account import configure, snapshot, mark

    a, b = fleet(tmp_path)
    configure(a.L, 100000)
    a.record_equity(100000)
    b.record_equity(100000)
    a.record_trade(entry_at="x", exit_at="y", qty=1, entry_px=100, exit_px=200, bars=1, exit_reason="x", pnl=100, slippage=0)
    a.set_position("SPY", 10, 500, "x", 0)
    b.set_position("QQQ", -5, 400, "x", 0)
    b.set_position("SPY   261009C00500000", 2, 5, "x", 0)
    for s, p in [("SPY", 510), ("QQQ", 390), ("SPY   261009C00500000", 6)]:
        mark(a.L, s, p, now())
    value = snapshot(a.L)
    assert value["equity"] == 100450  # +100 realized +100 long +50 short +200 options
    assert value["source"] == "paper" and value["ready"]
    assert value["gross"] == 8250
    configure(a.L, 100000)  # idempotent, never resets P&L or baseline
    assert snapshot(a.L)["equity"] == 100450
    with pytest.raises(ValueError):
        configure(a.L, 500000)


def test_missing_stale_or_future_marks_refuse_equity_without_trapping_exit(tmp_path):
    from cc_sdk.paper_account import configure, snapshot, mark

    a, _ = fleet(tmp_path)
    configure(a.L, 100000)
    a.set_position("SPY", 10, 500, "x", 0)
    o = Order("BUY", 1, "MKT", "QQQ", 400)
    assert snapshot(a.L)["equity"] is None
    assert not a.risk.pre_trade(o).ok
    assert a.risk.pre_trade(Order("SELL", 10, "MKT", "SPY", 500, reduces_risk=True)).ok
    for at in (now() - timedelta(seconds=91), now() + timedelta(seconds=31)):
        mark(a.L, "SPY", 510, at)
        assert not snapshot(a.L)["ready"]
    mark(a.L, "SPY", 510, now())
    assert a.risk.pre_trade(o).ok


def test_flat_paper_fleet_has_valid_capital_and_blocks_excess_exposure(tmp_path):
    from cc_sdk.paper_account import configure, snapshot

    a, _ = fleet(tmp_path)
    configure(a.L, 100000)
    assert snapshot(a.L)["equity"] == 100000
    a.L.set_limit("portfolio", "max_gross_exposure", 0.01)
    assert not a.risk.pre_trade(Order("BUY", 3, "MKT", "SPY", 500)).ok


def test_missing_account_equity_rejects_entry(tmp_path):
    a, _ = fleet(tmp_path)
    result = a.risk.pre_trade(Order("BUY", 1, "MKT", "SPY", 500))
    assert not result.ok and "account_equity" in result.reason


def test_paper_daily_loss_blocks_entry_before_monitor_and_allows_exit(tmp_path):
    from cc_sdk.paper_account import configure, mark

    a, _ = fleet(tmp_path)
    configure(a.L, 100000)
    a.set_position("SPY", 100, 500, "x", 0)
    mark(a.L, "SPY", 470, now())  # 3% account loss, exceeds 2% daily limit
    result = a.risk.pre_trade(Order("BUY", 1, "MKT", "QQQ", 400))
    assert not result.ok and "daily_loss" in result.reason
    assert a.risk.pre_trade(Order("SELL", 100, "MKT", "SPY", 470, reduces_risk=True)).ok


def test_actual_paper_exit_is_atomic_for_other_ledger_readers(tmp_path, monkeypatch):
    from cc_sdk.paper_account import configure, mark, snapshot
    from cc_sdk.ledger import Ledger
    from cc_sdk.intraday import SessionRunner, OpenPos

    a, _ = fleet(tmp_path)
    configure(a.L, 100000)
    a.set_position("SPY", 100, 500, "x", 0)
    mark(a.L, "SPY", 550, now())
    observer = Ledger(tmp_path / "cc.db")
    runner = SessionRunner(a, None, None, ["SPY"])
    runner.open["SPY"] = OpenPos("SPY", 1, 100, 500, 495, None, "x", None)
    original = a.record_trade
    intermediate = []

    def trade(**kwargs):
        value = original(**kwargs)
        intermediate.append(snapshot(observer)["equity"])
        return value

    monkeypatch.setattr(a, "record_trade", trade)
    runner._exit(runner.open["SPY"], 550, 0, "test")
    assert intermediate == [105000]  # reader sees entire pre-close state until commit
    assert snapshot(observer)["equity"] == pytest.approx(104994.5)
    observer.conn.close()


def test_valuation_reads_one_sqlite_snapshot_across_a_concurrent_close(tmp_path, monkeypatch):
    from cc_sdk.paper_account import configure, mark, snapshot
    from cc_sdk.ledger import Ledger

    a, _ = fleet(tmp_path)
    configure(a.L, 100000)
    a.set_position("SPY", 100, 500, "x", 0)
    mark(a.L, "SPY", 550, now())
    writer = Ledger(tmp_path / "cc.db")
    original = a.L.one
    fired = []

    def one(sql, params=()):
        result = original(sql, params)
        if "SUM(pnl)" in sql and not fired:
            fired.append(True)
            with writer.transaction():
                writer.trade(
                    a.m.id,
                    entry_at="x",
                    exit_at="y",
                    qty=100,
                    entry_px=500,
                    exit_px=550,
                    bars=1,
                    exit_reason="x",
                    pnl=5000,
                    slippage=0,
                )
                writer.set_position(a.m.id, "SPY", 0, None, None, 0)
        return result

    monkeypatch.setattr(a.L, "one", one)
    assert snapshot(a.L)["equity"] == 105000
    writer.conn.close()


def test_whole_option_spread_must_fit_shared_gross_exposure(tmp_path):
    from cc_sdk.paper_account import configure

    a, _ = fleet(tmp_path)
    configure(a.L, 100000)
    legs = [
        Order("BUY_TO_OPEN", 20, "LMT", "SPY   261009C00500000", 50),
        Order("SELL_TO_OPEN", 20, "LMT", "SPY   261009C00505000", 49),
    ]
    result = a.risk.pre_trade_spread(legs, 1)
    assert not result.ok and "max_gross_exposure" in result.reason
    assert len(a.L.q("SELECT id FROM orders WHERE status='rejected'")) == 2


def test_pending_opening_order_reserves_shared_capacity(tmp_path):
    from cc_sdk.paper_account import configure, snapshot

    a, _ = fleet(tmp_path)
    configure(a.L, 100000)
    a.L.order(
        a.m.id, side="BUY", qty=200, type_="MOC", symbol="SPY", status="sent", reason="pending", ref_price=500, risk_result={}
    )
    assert snapshot(a.L)["gross"] == 100000
    assert not a.risk.pre_trade(Order("BUY", 150, "MKT", "QQQ", 400)).ok


def test_daily_paper_buy_fill_and_position_are_published_atomically(tmp_path, monkeypatch):
    import importlib.util
    from pathlib import Path
    from cc_sdk.ledger import Ledger
    from cc_sdk.paper_account import configure, snapshot

    monkeypatch.setenv("CC_VAR", str(tmp_path))
    monkeypatch.setenv("MODE", "paper")
    a, _ = fleet(tmp_path)
    spec = importlib.util.spec_from_file_location(
        "daily_cc_atomic", Path(__file__).resolve().parents[2] / "bots/spy_mr_bot/cc.py"
    )
    cc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cc)
    configure(a.L, 100000)
    cc.bot.L.order(
        "spy_mr", side="BUY", qty=100, type_="MOC", symbol="SPY", status="sent", reason="pending", ref_price=500, risk_result={}
    )
    observer = Ledger(tmp_path / "cc.db")
    original = cc.bot.record_fill
    during = []

    def fill(*args, **kwargs):
        value = original(*args, **kwargs)
        during.append(snapshot(observer)["gross"])
        return value

    monkeypatch.setattr(cc.bot, "record_fill", fill)
    cc.record_fill("BUY", 100, 500, 500)
    assert during == [50000]
    assert cc.bot.positions()[0]["qty"] == 100
    observer.conn.close()
    cc.bot.L.conn.close()


def test_daily_entry_rejection_retains_audit_after_transaction(tmp_path, monkeypatch):
    import importlib.util
    from pathlib import Path
    from cc_sdk.paper_account import configure

    monkeypatch.setenv("CC_VAR", str(tmp_path))
    monkeypatch.setenv("MODE", "paper")
    a, _ = fleet(tmp_path)
    spec = importlib.util.spec_from_file_location(
        "daily_cc_rejection", Path(__file__).resolve().parents[2] / "bots/spy_mr_bot/cc.py"
    )
    cc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cc)
    configure(a.L, 100000)
    with pytest.raises(cc.Rejected):
        cc.guarded(
            cc._NullRun(),
            side="BUY",
            qty=3000,
            type_="MOC",
            symbol="SPY",
            ref_price=500,
            reduces_risk=False,
            send=lambda: "should-never-send",
        )
    assert cc.bot.L.one("SELECT COUNT(*) n FROM orders WHERE status='rejected'")["n"] == 1
    assert cc.bot.L.one("SELECT COUNT(*) n FROM alerts WHERE kind='order_rejected'")["n"] == 1
    cc.bot.L.conn.close()
