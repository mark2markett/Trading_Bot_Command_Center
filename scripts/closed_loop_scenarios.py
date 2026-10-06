"""Deterministic SYNTHETIC inputs drive actual manifests, strategies, runners and paper broker."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from cc_sdk.intraday import ET, Bar, SessionRunner
from cc_sdk.ledger import set_clock
from cc_sdk.options import OptionQuote, occ_symbol
from cc_sdk.options_runner import SpreadSessionRunner

from scripts.closed_loop_sources import load_fleet

DAY = datetime(2026, 10, 5, tzinfo=ET)


class ScriptedFeed:
    """An explicit synthetic gap/range breakout and toy chain, not historical market data."""
    def __init__(self, *, stale: bool = False, breakout: bool = True):
        self.spot = 572.0
        self.stale = stale
        self.breakout = breakout
        self.clock = DAY.replace(hour=10, minute=1)

    def quote(self, symbol):
        return self.spot, 0.0

    def daily_bars(self, symbol, n):
        return [Bar(DAY - timedelta(days=30 - i), 565, 567.5, 562.5, 565, 1_000_000) for i in range(30)][-n:]

    def minute_bars(self, symbol, day):
        start = DAY.replace(hour=9, minute=30)
        bars = [Bar(start + timedelta(minutes=i), 570, 571, 569, 570.5, 1000) for i in range(30)]
        return bars + [Bar(start + timedelta(minutes=30), 570.5, 572.5 if self.breakout else 571, 570,
                           572 if self.breakout else 570.5, 2000)]

    def chain(self, symbol, from_date, to_date, strike_count=40):
        expiry = DAY.date() + timedelta(days=2)
        quotes = []
        for strike in range(560, 586, 5):
            for right in ("C", "P"):
                intrinsic = max(0, self.spot - strike) if right == "C" else max(0, strike - self.spot)
                mid = round(intrinsic + max(0.05, 1 - 0.1 * abs(strike - self.spot)), 2)
                delta = 0.5 if strike == 570 else (0.3 if strike > 570 else 0.7)
                quotes.append(OptionQuote(occ_symbol(symbol, expiry, right, strike), symbol, expiry, float(strike), right,
                                          mid - 0.02, mid + 0.02, mid, delta if right == "C" else delta - 1,
                                          -0.3, 0.18, 1000, 100, self.clock.timestamp() - (500 if self.stale else 1), 2))
        return quotes


@dataclass
class ScenarioContext:
    repo: Path
    runtime: Path
    bots: dict
    modules: dict
    feeds: dict = field(default_factory=dict)
    runners: dict = field(default_factory=dict)

    @property
    def daily(self):
        return self.modules["spy_mr"]

    def close(self) -> None:
        set_clock(None)
        for bot in self.bots.values():
            bot.L.conn.close()
        root = logging.getLogger()
        for handler in list(root.handlers):
            filename = getattr(handler, "baseFilename", None)
            if filename and Path(filename).is_relative_to(self.runtime.parent):
                root.removeHandler(handler)
                handler.close()


def make_scenarios(repo: Path, runtime: Path) -> ScenarioContext:
    bots, modules = load_fleet(repo, runtime)
    next(iter(bots.values())).record_equity(100_000, source="broker")  # SYNTHETIC shared account in disposable ledger
    return ScenarioContext(repo, runtime, bots, modules)


def step(context: ScenarioContext, bot_id: str, hour: int, minute: int) -> None:
    feed = context.feeds[bot_id]
    feed.clock = DAY.replace(hour=hour, minute=minute)
    try:
        set_clock(lambda: feed.clock)
        context.runners[bot_id].step(feed.clock)
    finally:
        set_clock(None)


def run_equity(context: ScenarioContext, bot_id: str) -> str:
    module, bot = context.modules[bot_id], context.bots[bot_id]
    rules = {"gap_go": "GapGoRules", "nr7": "NR7Rules", "sip_orb": "SipOrbRules"}
    feed = ScriptedFeed()
    runner = SessionRunner(bot, feed, getattr(module, rules[bot_id])(), ["SPY"], adopt_positions=False)
    context.feeds[bot_id], context.runners[bot_id] = feed, runner
    runner.prepare(DAY)
    step(context, bot_id, 10, 1)
    assert "SPY" in runner.open, f"{bot_id}: actual rules did not open a paper position"
    step(context, bot_id, 15, 58)
    assert not runner.open and not bot.positions(), f"{bot_id}: end-of-day exit did not flatten"
    trades = bot.L.one("SELECT COUNT(*) n FROM trades WHERE bot_id=?", (bot_id,))["n"]
    fills = bot.L.one("SELECT COUNT(*) n FROM fills WHERE bot_id=?", (bot_id,))["n"]
    assert trades and fills >= 2, f"{bot_id}: expected trade and fills missing"
    return f"Actual {rules[bot_id]} -> risk -> paper entry/EOD exit; {trades} trade(s), {fills} fills"


def run_spread(context: ScenarioContext, *, stale: bool = False) -> str:
    bot = context.bots["gap_go_spread"]
    feed = ScriptedFeed(stale=stale)
    runner = SpreadSessionRunner(bot, feed, context.modules["gap_go_spread"].GapGoRules(), ["SPY"], adopt_positions=False)
    context.feeds["gap_go_spread"], context.runners["gap_go_spread"] = feed, runner
    runner.prepare(DAY)
    step(context, "gap_go_spread", 10, 1)
    if stale:
        assert not runner.open and not bot.positions(), "Stale chain produced an entry"
        row = bot.L.one("SELECT reason FROM decisions WHERE bot_id='gap_go_spread' AND action='NONE' ORDER BY id DESC")
        assert row and "old" in row["reason"], "Stale chain refusal not recorded"
        return "Actual fill model refused a 500-second-old chain; NONE decision persisted"
    assert "SPY" in runner.open and len(bot.positions()) == 2, "Gap-go spread did not open both legs"
    assert bot.L.one("SELECT 1 FROM kv WHERE key='optlive:gap_go_spread:SPY'"), "Live Greeks absent from ledger"
    return f"Actual GapGoRules opened two OCC legs, qty={runner.open['SPY'].qty}; optlive Greeks persisted"


class DailyFeed:
    def __init__(self, day: datetime):
        self.clock = day
        self.bars = [{"date": (day - timedelta(days=250 - i)).date().isoformat(),
                      "open": 100 + i * 0.1, "high": 100.5 + i * 0.1, "low": 99.5 + i * 0.1,
                      "close": 100 + i * 0.1} for i in range(250)]
        self.bars[-1]["close"] *= 0.985
        self.live = self.bars[-1]["close"] * 0.985

    def daily_closes(self, symbol, n=260):
        return self.bars[-n:]

    def last_price(self, symbol):
        return self.live

    def add_close(self, close: float, day: datetime, low: float | None = None) -> None:
        self.bars.append({"date": day.date().isoformat(), "open": close, "high": close + 0.5,
                          "low": low if low is not None else close - 0.5, "close": close})
        self.live = close


def run_daily_lifecycle(context: ScenarioContext, *, crash: bool = False) -> str:
    module, bot = context.daily, context.bots["spy_mr"]
    day = DAY + timedelta(days=7 if crash else 0)
    feed = DailyFeed(day)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return feed.clock.astimezone(tz) if tz else feed.clock.replace(tzinfo=None)

    old_datetime = module.datetime
    module.datetime = Clock
    module.STATE_PATH = context.runtime / ("daily-crash-state.json" if crash else "daily-state.json")
    paper = module.PaperBroker(str(context.runtime / ("daily-crash-paper.json" if crash else "daily-paper.json")),
                               100_000, data=feed)
    state = module.load_state()
    try:
        set_clock(lambda: feed.clock)
        with module.cc.run("decide") as run:
            module.cmd_decide(paper, state, run)
        assert state.get("pending") and state["pending"]["side"] == "BUY", "Daily MR entry did not queue"
        feed.add_close(feed.live, day)
        feed.clock = day + timedelta(days=1)
        with module.cc.run("reconcile") as run:
            module.cmd_reconcile(paper, state, run)
        assert state["in_position"] and state["stop_order_id"], "Daily MR fill or protective stop absent"
        if crash:
            entry = state["entry_price"]
            feed.add_close(entry * 0.93, day + timedelta(days=1), low=entry * 0.92)
        else:
            feed.add_close(feed.live * 1.04, day + timedelta(days=1))
            with module.cc.run("decide") as run:
                module.cmd_decide(paper, state, run)
            assert state["pending"]["side"] == "SELL", "Daily MR exit did not queue"
        feed.clock = day + timedelta(days=2)
        with module.cc.run("reconcile") as run:
            module.cmd_reconcile(paper, state, run)
        assert not state["in_position"] and paper.position("SPY") == 0 and not bot.positions(), "Daily MR did not flatten"
        reason = "crash_stop" if crash else "exit_sma"
        assert bot.L.one("SELECT 1 FROM trades WHERE bot_id='spy_mr' AND exit_reason=?", (reason,)), "Daily MR closed trade absent"
        return f"Actual cmd_decide/cmd_reconcile/PaperBroker: entry, 5% stop, {reason}, persisted trade; controlled calendar"
    finally:
        module.datetime = old_datetime
        set_clock(None)
