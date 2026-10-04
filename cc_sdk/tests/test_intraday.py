"""Intraday runner: replay parity with the research rules, controls honored mid-session, EOD flatten, sizing, scanner."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from cc_sdk import Bot, BotManifest
from cc_sdk.control import Control
from cc_sdk.intraday import ET, Bar, DayContext, ReplayFeed, SessionRunner, Signal, day_context, minutes_of, size_by_risk

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "bots" / "gap_go_bot"))
sys.path.insert(0, str(ROOT / "bots" / "sip_orb"))
from gap_go_rules import GapGoRules  # noqa: E402
from sip_scanner import filter_rank  # noqa: E402

DAY = datetime(2024, 3, 5, tzinfo=ET)


def mk_bars(day: datetime, closes: list[float], spread: float = 0.2) -> list[Bar]:
    out = []
    for t, c in zip(minutes_of(day, 570, 959), closes, strict=False):
        out.append(Bar(t, c, c + spread, c - spread, c, 1000))
    return out


def daily_history(day: datetime, close: float = 100.0, rng: float = 2.0, n: int = 40) -> list[Bar]:
    out = []
    for i in range(n, 0, -1):
        t = day - timedelta(days=i)
        out.append(Bar(t, close, close + rng / 2, close - rng / 2, close, 1e6))
    return out


def make_bot(tmp_path: Path, bot_id: str = "t_gap") -> Bot:
    var = tmp_path / "var"
    (var / "control").mkdir(parents=True)
    m = BotManifest(id=bot_id, name="T", version="0", strategy_line="", instrument="SPY", mode="paper",
                    limits={"max_position_usd": 1_000_000, "max_order_qty": 100_000, "max_orders_per_day": 10})
    return Bot(m, db_path=var / "cc.db", control_dir=var / "control")


def replay(bot: Bot, feed: ReplayFeed, rules, symbols: list[str], **kw) -> SessionRunner:
    r = SessionRunner(bot, feed, rules, symbols, **kw)
    r.prepare(DAY)
    for t in minutes_of(DAY):
        feed.clock = t
        r.step(t)
    return r


def gap_up_day() -> list[float]:
    # prior close 100; open 101 (+100 bp); 30-min range 100.8–101.3; breakout at 10:05; drift up to 102
    closes = [101.0 + (0.3 if i % 2 else -0.2) for i in range(30)]
    closes += [101.1, 101.2, 101.3, 101.4, 101.6]            # 10:00–10:04 (bar 33 closes 101.6 > 101.5 hi)
    closes += [101.6 + 0.4 * k / 355 for k in range(355)]
    return closes


def test_gap_go_replay_matches_research_rules(tmp_path):
    """The incremental bot rules must enter on the same bar, same side, same stop as research/strategies.py::gap_go."""
    from research.data import Day
    from research.strategies import gap_go
    import numpy as np

    bars = mk_bars(DAY, gap_up_day())
    feed = ReplayFeed({"SPY": bars}, {"SPY": daily_history(DAY)})
    bot = make_bot(tmp_path)
    r = replay(bot, feed, GapGoRules(70, 30), ["SPY"])
    trades = bot.L.q("SELECT * FROM trades WHERE bot_id='t_gap'")
    assert len(trades) == 1 and trades[0]["qty"] > 0 and trades[0]["exit_reason"] == "eod"
    # research version on the same bars
    d = Day(date=DAY, mod=np.array([b.mod for b in bars]), o=np.array([b.o for b in bars]), h=np.array([b.h for b in bars]),
            l=np.array([b.l for b in bars]), c=np.array([b.c for b in bars]), v=np.array([b.v for b in bars]),
            prev_close=100.0, prev_high=101.0, prev_low=99.0, prev_range=2.0, atr14=2.0, nr7=False, vol_profile=None)
    rt = gap_go(d, {"gap_bps": 70, "wait_min": 30})
    assert len(rt) == 1 and rt[0].side == 1
    entry_bar = bars[rt[0].entry_i]
    assert trades[0]["entry_at"] is not None
    sent = bot.L.one("SELECT stop_price, ref_price FROM orders WHERE bot_id='t_gap' AND side='BUY'")
    assert sent["stop_price"] == pytest.approx(min(b.l for b in bars[:30]))
    assert sent["ref_price"] == pytest.approx(entry_bar.o)   # filled at the open of the bar after the signal bar
    assert r.realized > 0


def test_no_trade_without_gap(tmp_path):
    bars = mk_bars(DAY, [100.0 + 0.001 * i for i in range(390)])
    feed = ReplayFeed({"SPY": bars}, {"SPY": daily_history(DAY)})
    bot = make_bot(tmp_path)
    replay(bot, feed, GapGoRules(70, 30), ["SPY"])
    assert bot.L.one("SELECT COUNT(*) n FROM trades")["n"] == 0


def test_kill_mid_session_flattens_and_blocks_entries(tmp_path):
    bars = mk_bars(DAY, gap_up_day())
    feed = ReplayFeed({"SPY": bars}, {"SPY": daily_history(DAY)})
    bot = make_bot(tmp_path)
    r = SessionRunner(bot, feed, GapGoRules(70, 30), ["SPY"])
    r.prepare(DAY)
    for t in minutes_of(DAY):
        feed.clock = t
        if t.hour == 11 and t.minute == 0:
            Control.write_flag(bot.control.dir / "KILL", {"actor": "test"})
        r.step(t)
    tr = bot.L.q("SELECT exit_reason, exit_at FROM trades")
    assert len(tr) == 1 and tr[0]["exit_reason"] == "kill"
    assert not r.open and bot.positions() == []


def test_flatten_flag_cleared_after_exit(tmp_path):
    bars = mk_bars(DAY, gap_up_day())
    feed = ReplayFeed({"SPY": bars}, {"SPY": daily_history(DAY)})
    bot = make_bot(tmp_path)
    r = SessionRunner(bot, feed, GapGoRules(70, 30), ["SPY"])
    r.prepare(DAY)
    for t in minutes_of(DAY):
        feed.clock = t
        if (t.hour, t.minute) == (12, 0):
            Control.write_flag(bot.control.dir / "t_gap.flatten", {"actor": "test"})
        r.step(t)
        if (t.hour, t.minute) == (12, 1):
            assert not bot.control.flatten_requested()
    assert bot.L.one("SELECT exit_reason FROM trades")["exit_reason"] == "flatten"
    assert bot.L.one("SELECT COUNT(*) n FROM trades")["n"] == 1   # no re-entry after flatten (one trade per symbol per day)


def test_stop_hit_exits(tmp_path):
    closes = gap_up_day()
    closes[60:] = [100.5] * (390 - 60)      # 10:30 onward collapses below the range low
    bars = mk_bars(DAY, closes)
    feed = ReplayFeed({"SPY": bars}, {"SPY": daily_history(DAY)})
    bot = make_bot(tmp_path)
    r = replay(bot, feed, GapGoRules(70, 30), ["SPY"])
    assert bot.L.one("SELECT exit_reason FROM trades")["exit_reason"] == "stop" and r.realized < 0


def test_sizing_and_context():
    assert size_by_risk(100.0, 99.0, 1_000, 1_000_000, 100_000) == 1000
    assert size_by_risk(100.0, 99.0, 1_000, 50_000, 100_000) == 500
    assert size_by_risk(100.0, 100.0, 1_000, 50_000, 100_000) == 0
    ctx = day_context(daily_history(DAY))
    assert ctx.atr14 == pytest.approx(2.0) and ctx.nr7 is True and ctx.prev_close == 100.0
    s = Signal(1, "x", stop_offset=0.5, target_r=2.0)
    assert s.resolve(100.0) == (99.5, 101.0)


def test_scanner_filter_rank():
    rows = [{"symbol": "aaa", "price": 12, "rvol": 5, "atr14": 1.0, "avg_vol": 2e6},
            {"symbol": "BBB", "price": 3, "rvol": 9, "atr14": 1.0, "avg_vol": 2e6},        # price too low
            {"symbol": "CCC", "price": 30, "rvol": 7, "atr14": 0.2, "avg_vol": 2e6},       # ATR too small
            {"symbol": "DDD", "price": 30, "rvol": 8, "atr14": 2.0, "avg_vol": 5e5},       # volume too thin
            {"symbol": "EEE", "price": 30, "rvol": 6, "atr14": 2.0, "avg_vol": 5e6},
            {"symbol": "EEE", "price": 30, "rvol": 6, "atr14": 2.0, "avg_vol": 5e6},       # duplicate
            {"symbol": "FFF", "rvol": 99}]                                                   # malformed
    assert filter_rank(rows, 20) == ["EEE", "AAA"]
    assert filter_rank(rows, 1) == ["EEE"]


def test_late_universe_binding(tmp_path):
    bars = mk_bars(DAY, gap_up_day())
    feed = ReplayFeed({"XYZ": bars}, {"XYZ": daily_history(DAY)})
    bot = make_bot(tmp_path, "t_sip")
    calls = []

    def uni(now):
        calls.append(now)
        return ["XYZ"]
    r = SessionRunner(bot, feed, GapGoRules(70, 30), [], universe_fn=uni, universe_at_mod=575)
    r.prepare(DAY)
    for t in minutes_of(DAY):
        feed.clock = t
        r.step(t)
    assert len(calls) == 1 and calls[0].minute == 35 and r.symbols == ["XYZ"]
    assert bot.L.one("SELECT COUNT(*) n FROM trades")["n"] == 1
    assert bot.L.one("SELECT action FROM decisions WHERE action='UNIVERSE'")


def test_day_context_needs_history():
    with pytest.raises(ValueError):
        day_context(daily_history(DAY, n=5))
    assert isinstance(DayContext(1, 1, 1, 1), DayContext)


def test_replay_clock_stamps_records_and_isolates_risk_counters(tmp_path):
    """Replayed trades carry the replayed date, so a replay never consumes today's orders-per-day budget."""
    from cc_sdk.ledger import set_clock

    bars = mk_bars(DAY, gap_up_day())
    feed = ReplayFeed({"SPY": bars}, {"SPY": daily_history(DAY)})
    bot = make_bot(tmp_path)
    try:
        set_clock(lambda: feed.clock)
        replay(bot, feed, GapGoRules(70, 30), ["SPY"], adopt_positions=False)
    finally:
        set_clock(None)
    tr = bot.L.one("SELECT entry_at, exit_at FROM trades")
    assert tr["entry_at"].startswith("2024-03-05") and tr["exit_at"].startswith("2024-03-05")
    assert bot.L.orders_today("t_gap", datetime.now(ET).date().isoformat()) == []
    # a second replay of the same day is refused by the per-symbol duplicate guard, not by a rules change
    try:
        set_clock(lambda: feed.clock)
        replay(bot, feed, GapGoRules(70, 30), ["SPY"], adopt_positions=False)
    finally:
        set_clock(None)
    assert bot.L.one("SELECT COUNT(*) n FROM trades")["n"] == 1
    assert bot.L.one("SELECT reason FROM decisions WHERE action='NONE' ORDER BY id DESC LIMIT 1")["reason"].startswith("rejected: duplicate")


def test_cli_replay_never_writes_the_live_ledger(tmp_path, monkeypatch):
    """`bot.py replay` runs in a throwaway ledger: its trades are reported, but never enter the live paper record
    (a 2026-10-03 replay put a fake SPY trade into gap_go's paper history)."""
    from cc_sdk import intraday_cli
    from cc_sdk.ledger import Ledger

    var = tmp_path / "var"
    (var / "control").mkdir(parents=True)
    monkeypatch.setenv("CC_VAR", str(var))
    feed = ReplayFeed({"SPY": mk_bars(DAY, gap_up_day())}, {"SPY": daily_history(DAY)})
    monkeypatch.setattr(intraday_cli, "replay_feed", lambda *a: feed)
    m = BotManifest(id="t_live", name="T", version="0", strategy_line="", instrument="SPY", mode="paper",
                    limits={"max_position_usd": 1_000_000, "max_order_qty": 100_000, "max_orders_per_day": 10})
    out = intraday_cli.replay_isolated(m, GapGoRules(70, 30), "SPY", "X", DAY.date().isoformat())
    assert len(out["trades"]) == 1                       # the replay itself still trades and reports
    live = Ledger(var / "cc.db")
    for t in ("trades", "orders", "fills", "decisions", "heartbeats"):
        assert live.one(f"SELECT COUNT(*) n FROM {t}")["n"] == 0, t
