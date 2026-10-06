"""M7.4 + M7.5 — the spread runner end to end on a scripted feed, and the honesty report."""
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from cc_sdk import Bot, BotManifest
from cc_sdk.intraday import ET, Bar, Signal
from cc_sdk.options import OptionQuote, occ_symbol, spread_pnl
from cc_sdk.options_report import options_report
from cc_sdk.options_runner import OpenSpread, SpreadSessionRunner, pick_vertical

DAY = datetime(2026, 10, 5, tzinfo=ET)                     # a Monday
EXP = date(2026, 10, 7)                                    # 2 days out


class Feed:
    """Scripted underlying + a toy chain: intrinsic + time value that falls 0.10 per point from the money (floor 0.05),
    quoted with a 0.04 spread at 'now'. Daily bars have a 5-point true range, so ATR(14) = 5."""

    def __init__(self, spot=570.0, stale=False):
        self.spot, self.stale, self.clock = spot, stale, DAY.replace(hour=10, minute=1)
        self.chain_calls = 0

    def quote(self, s):
        return self.spot, 0.0

    def minute_bars(self, s, day):
        t = DAY.replace(hour=9, minute=30)
        return [Bar(t + timedelta(minutes=i), 570, 571, 569, 570, 1000) for i in range(31)]

    def daily_bars(self, s, n):
        return [Bar(DAY - timedelta(days=30 - i), 565, 567.5, 562.5, 565, 1e6) for i in range(30)][-n:]

    def chain(self, s, f, t, strike_count=40):
        self.chain_calls += 1
        ts = self.clock.timestamp() - (500 if self.stale else 1)
        out = []
        for k in range(560, 586, 5):
            for right in ("C", "P"):
                iv = max(0.0, self.spot - k) if right == "C" else max(0.0, k - self.spot)
                mid = round(iv + max(0.05, 1.0 - 0.1 * abs(k - self.spot)), 2)
                d = 0.5 if k == 570 else (0.3 if k > 570 else 0.7)
                out.append(OptionQuote(occ_symbol("SPY", EXP, right, k), "SPY", EXP, float(k), right, mid - 0.02, mid + 0.02,
                                       mid, d if right == "C" else d - 1, -0.3, 0.18, 1000, 100, ts, 2))
        return out


class Rules:
    name = "test_signal"

    def __init__(self, side=1):
        self.side = side

    def decide(self, bars, ctx):
        return Signal(self.side, "test signal", stop=565.0 if self.side > 0 else 575.0)


def mk(tmp_path: Path, **limits):
    cdir = tmp_path / "control"
    cdir.mkdir(exist_ok=True)
    m = BotManifest(id="spread_t", name="Spread test", version="0.1", strategy_line="x", instrument="SPY options", mode="paper",
                    cadence={"session": "09:25"}, limits={"max_orders_per_day": 8, **limits})
    bot = Bot(m, db_path=tmp_path / "cc.db", control_dir=cdir)
    bot.record_equity(100_000, source="broker")  # explicit synthetic account equity
    return bot, cdir


def run_to(runner, feed, hh, mm):
    feed.clock = DAY.replace(hour=hh, minute=mm)
    runner.step(feed.clock)


def test_pick_vertical_call_and_put():
    f = Feed()
    (lo, hi), _ = pick_vertical(f.chain("SPY", None, None), 570.2, +1, 5.0, DAY.date(), dte_min=2, dte_max=7, width_atr=1.0)
    assert (lo.right, lo.strike, hi.strike) == ("C", 570.0, 575.0)
    (lo, hi), _ = pick_vertical(f.chain("SPY", None, None), 570.2, -1, 5.0, DAY.date(), dte_min=2, dte_max=7, width_atr=1.0)
    assert (lo.right, lo.strike, hi.strike) == ("P", 570.0, 565.0)
    none, why = pick_vertical(f.chain("SPY", None, None), 570.2, +1, 5.0, DAY.date(), dte_min=3, dte_max=7, width_atr=1.0)
    assert none is None and "expiry" in why


def test_enter_then_eod_exit_records_spread_and_share_equivalent(tmp_path):
    bot, _ = mk(tmp_path)
    feed = Feed()
    r = SpreadSessionRunner(bot, feed, Rules(+1), ["SPY"], risk_pct=0.01, paper_equity=100_000, adopt_positions=False)
    r.prepare(DAY)
    run_to(r, feed, 10, 1)
    pos = r.open["SPY"]
    assert isinstance(pos, OpenSpread) and pos.right == "C" and pos.qty > 0
    # 570C mid 1.00 bought at 1.01; 575C (one ATR out) mid 0.50 sold at 0.49; risk $1,000 / $52 per spread = 19
    assert pos.entry_prices == pytest.approx([1.01, 0.49]) and pos.qty == 19
    assert pos.net_debit == pytest.approx(0.52) and pos.net_delta == pytest.approx(0.2)
    legs = {p["symbol"]: p["qty"] for p in bot.positions()}
    assert legs == {pos.legs[0]: pos.qty, pos.legs[1]: -pos.qty}
    assert bot.L.one("SELECT COUNT(*) n FROM kv WHERE key='spread:spread_t:SPY'")["n"] == 1

    feed.spot = 572.0                                                # underlying up 2.00 by the close
    run_to(r, feed, 15, 58)
    assert "SPY" not in r.open and bot.positions() == []
    t = bot.L.one("SELECT * FROM option_trades")
    # at 572: 570C mid 2.80 sold at 2.79; 575C mid 0.70 bought back at 0.71
    want = spread_pnl(entry=[1.01, 0.49], exit=[2.79, 0.71], signs=[1, -1], qty=pos.qty)
    assert want == pytest.approx(1.56 * 19 * 100)
    assert t["spread_pnl"] == pytest.approx(want)
    assert t["share_equiv_pnl"] == pytest.approx(0.2 * 100 * pos.qty * 2.0)
    assert bot.L.one("SELECT exit_reason FROM trades")["exit_reason"] == "eod"
    assert bot.L.one("SELECT COUNT(*) n FROM kv")["n"] == 0
    statuses = [row["side"] for row in bot.L.q("SELECT side FROM orders WHERE status IN ('sent','filled') ORDER BY id")]
    assert statuses == ["BUY_TO_OPEN", "SELL_TO_OPEN", "SELL_TO_CLOSE", "BUY_TO_CLOSE"]


def test_underlying_stop_closes_the_spread(tmp_path):
    bot, _ = mk(tmp_path)
    feed = Feed()
    r = SpreadSessionRunner(bot, feed, Rules(+1), ["SPY"], adopt_positions=False)
    r.prepare(DAY)
    run_to(r, feed, 10, 1)
    feed.spot = 564.0                                                # through the 565 stop
    run_to(r, feed, 11, 0)
    assert "SPY" not in r.open
    assert bot.L.one("SELECT exit_reason FROM trades")["exit_reason"] == "stop"


def test_stale_chain_means_no_entry(tmp_path):
    bot, _ = mk(tmp_path)
    feed = Feed(stale=True)
    r = SpreadSessionRunner(bot, feed, Rules(+1), ["SPY"], adopt_positions=False)
    r.prepare(DAY)
    run_to(r, feed, 10, 1)
    assert r.open == {} and bot.positions() == []
    d = bot.L.one("SELECT action, reason FROM decisions WHERE action='NONE'")
    assert "old" in d["reason"]


def test_premium_cap_limits_size(tmp_path):
    bot, _ = mk(tmp_path, max_premium_usd=300)                      # one spread costs $52 -> at most 5
    feed = Feed()
    r = SpreadSessionRunner(bot, feed, Rules(+1), ["SPY"], risk_pct=0.05, adopt_positions=False)
    r.prepare(DAY)
    run_to(r, feed, 10, 1)
    assert r.open["SPY"].qty == 5                                   # risk alone would allow 96


def test_kill_flattens_and_crash_recovery_adopts(tmp_path):
    bot, cdir = mk(tmp_path)
    feed = Feed()
    r1 = SpreadSessionRunner(bot, feed, Rules(+1), ["SPY"])
    r1.prepare(DAY)
    run_to(r1, feed, 10, 1)
    assert "SPY" in r1.open
    # the process dies; a new session starts and must find the open spread
    bot2 = Bot(bot.m, db_path=tmp_path / "cc.db", control_dir=cdir)
    r2 = SpreadSessionRunner(bot2, feed, Rules(+1), ["SPY"])
    r2.prepare(DAY)
    assert isinstance(r2.open["SPY"], OpenSpread)
    (cdir / "KILL").write_text("{}")
    run_to(r2, feed, 10, 30)
    assert r2.open == {} and bot2.positions() == []
    assert bot2.L.one("SELECT exit_reason FROM trades")["exit_reason"] == "kill"


def test_report_says_when_the_spread_is_just_leverage():
    rows = [{"spread_pnl": 50.0, "share_equiv_pnl": 80.0, "und_entry": 570, "und_exit": 572}] * 15 + \
           [{"spread_pnl": -60.0, "share_equiv_pnl": -40.0, "und_entry": 570, "und_exit": 568}] * 10
    rep = options_report(rows)
    assert rep["trades"] == 25 and rep["n_up"] == 15 and rep["n_down"] == 10
    assert rep["excess_vs_shares"] == pytest.approx(25 * 0 + 15 * -30 + 10 * -20)
    assert "Not beating" in rep["verdict"] and "leverage" in rep["verdict"]
    assert options_report(rows[:5])["verdict"].startswith("Too few trades")
    good = [{"spread_pnl": 90.0, "share_equiv_pnl": 50.0, "und_entry": 570, "und_exit": 572}] * 20
    assert options_report(good)["verdict"].startswith("Beating")


def test_live_greeks_recorded_refreshed_and_removed(tmp_path):
    import json as _json
    bot, _ = mk(tmp_path)
    feed = Feed()
    r = SpreadSessionRunner(bot, feed, Rules(+1), ["SPY"], adopt_positions=False)
    r.prepare(DAY)
    run_to(r, feed, 10, 1)
    key = "optlive:spread_t:SPY"
    live = _json.loads(bot.L.one("SELECT value_json FROM kv WHERE key=?", (key,))["value_json"])
    # 19 spreads, long 570C (delta 0.5, mid 1.00) / short 575C (delta 0.3, mid 0.50), paid 0.52
    assert live["right"] == "C" and live["strikes"] == [570.0, 575.0] and live["qty"] == 19 and live["dte"] == 2
    assert live["delta_shares"] == pytest.approx(0.2 * 100 * 19)
    assert live["theta_usd_day"] == pytest.approx(0.0)          # fixture gives both legs the same theta
    assert live["value_usd"] == pytest.approx(0.50 * 1900) and live["cost_usd"] == pytest.approx(0.52 * 1900)
    assert live["unrealized_usd"] == pytest.approx(-0.02 * 1900)
    feed.spot = 572.0
    run_to(r, feed, 10, 3)                                        # > 60 s later: refreshed from a new chain
    live2 = _json.loads(bot.L.one("SELECT value_json FROM kv WHERE key=?", (key,))["value_json"])
    assert live2["value_usd"] == pytest.approx((2.80 - 0.70) * 1900)
    run_to(r, feed, 15, 58)
    assert bot.L.one("SELECT COUNT(*) n FROM kv WHERE key=?", (key,))["n"] == 0
