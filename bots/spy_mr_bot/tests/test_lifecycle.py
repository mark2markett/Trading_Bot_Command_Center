"""End-to-end: synthetic feed -> decide -> reconcile -> entry -> stop/exit, in paper mode."""
import json, os, sys, pathlib, importlib, tempfile
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "cc_sdk"))
os.environ["MODE"] = "paper"; os.environ["SCHWAB_API_KEY"] = ""
_VAR = pathlib.Path(tempfile.mkdtemp()) / "var"; (_VAR / "control").mkdir(parents=True)
os.environ["CC_VAR"] = str(_VAR)


class Feed:
    """Daily bars we control; `today` advances as the test calls step()."""
    def __init__(self):
        self.bars = [{"date": f"2026-01-{i:02d}", "open": 100+i*.1, "high": 100.5+i*.1, "low": 99.5+i*.1, "close": 100+i*.1}
                     for i in range(1, 29)]
        while len(self.bars) < 250:
            n = len(self.bars); c = 100 + n * .1
            self.bars.append({"date": f"2026-02-{n:03d}", "open": c, "high": c+.5, "low": c-.5, "close": c})
        self.live = self.bars[-1]["close"]
    def daily_closes(self, sym, n=260): return self.bars[-n:]
    def last_price(self, sym): return self.live
    def step(self, close, low=None, date=None):
        date = date or f"2026-03-{len(self.bars):03d}"
        self.bars.append({"date": date, "open": close, "high": close+.5, "low": low if low is not None else close-.5, "close": close})
        self.live = close


def run(tmp_path, monkeypatch):
    import bot
    importlib.reload(bot)
    bot.STATE_PATH = tmp_path / "state.json"; bot.LOG_PATH = tmp_path / "bot.log"
    from broker import PaperBroker
    feed = Feed()
    b = PaperBroker(str(tmp_path / "ledger.json"), 100_000, data=feed)
    bot.cc.bot.record_equity(100000, source="broker")  # synthetic account fixture
    st = bot.load_state()
    # Day 1: two sharp down days -> RSI2 < 10 while still above SMA200 -> BUY queued
    feed.step(feed.live * 0.985); feed.live = feed.bars[-1]["close"] * 0.985
    monkeypatch.setattr(bot, "trading_day_today", lambda: True)
    bot.cmd_decide(b, st)
    assert st["pending"]["side"] == "BUY" and st["pending"]["qty"] > 0
    st["pending"]["date"] = "2026-03-10"  # synthetic calendar
    # Next morning: bar for that day arrives at the provisional price -> fill confirmed, stop placed
    feed.step(feed.live, date="2026-03-10")
    bot.cmd_reconcile(b, st)
    assert st["in_position"] and st["qty"] == b.position("SPY") and st["stop_order_id"]
    stop = b.ledger["stops"]["SPY"]["stop"]
    assert abs(stop - round(st["entry_price"] * 0.95, 2)) < 1e-6
    # Day 2: price bounces above SMA5 -> SELL queued; next morning fill -> flat
    feed.step(feed.live * 1.04, date="2026-03-11")
    bot.cmd_decide(b, st)
    assert st["pending"]["side"] == "SELL" and st["pending"]["reason"] == "exit_sma"
    st["pending"]["date"] = "2026-03-11"
    bot.cmd_reconcile(b, st)
    assert not st["in_position"] and b.position("SPY") == 0 and b.ledger["stops"] == {}
    pnl = b.ledger["cash"] - 100_000
    assert pnl > 0
    return pnl, b.ledger["fills"]


def test_lifecycle(tmp_path, monkeypatch):
    pnl, fills = run(tmp_path, monkeypatch)
    assert len(fills) == 2 and fills[0]["kind"] == "BUY_MOC" and fills[1]["kind"] == "SELL_MOC"


def test_crash_stop(tmp_path, monkeypatch):
    import bot; importlib.reload(bot)
    bot.STATE_PATH = tmp_path / "state.json"; bot.LOG_PATH = tmp_path / "bot.log"
    from broker import PaperBroker
    feed = Feed(); b = PaperBroker(str(tmp_path / "ledger.json"), 100_000, data=feed); st = bot.load_state()
    monkeypatch.setattr(bot, "trading_day_today", lambda: True)
    feed.step(feed.live * 0.985); feed.live = feed.bars[-1]["close"] * 0.985
    bot.cmd_decide(b, st); st["pending"]["date"] = "2026-03-10"
    feed.step(feed.live, date="2026-03-10"); bot.cmd_reconcile(b, st)
    assert st["in_position"], st
    entry = st["entry_price"]
    # Crash day: low pierces the 5% stop. No sell was queued, so reconcile must detect the stop fill.
    feed.step(entry * 0.93, low=entry * 0.92, date="2026-03-11")
    bot.cmd_reconcile(b, st)
    assert not st["in_position"] and b.position("SPY") == 0
    assert b.ledger["fills"][-1]["kind"] == "STOP"
    assert b.ledger["cash"] < 100_000  # took the loss, as designed
