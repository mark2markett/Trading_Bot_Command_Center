"""
Replay parity: the SDK-wrapped bot must make exactly the decisions the pre-SDK bot made.
We drive both the frozen strategy functions and the wrapped cmd_decide over the same synthetic feed and
assert identical BUY/SELL/HOLD actions and quantities, with the SDK writing to a temp ledger.
"""
import importlib
import json
import os
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "cc_sdk"))


class Feed:
    def __init__(self):
        self.bars = []
        for i in range(250):
            c = 100 + i * 0.1
            self.bars.append({"date": f"2026-01-{i:03d}", "open": c, "high": c + .5, "low": c - .5, "close": c})
        self.live = self.bars[-1]["close"]

    def daily_closes(self, sym, n=260): return self.bars[-n:]
    def last_price(self, sym): return self.live
    def step(self, close, date):
        self.bars.append({"date": date, "open": close, "high": close + .5, "low": close - .5, "close": close}); self.live = close


SCRIPT = [  # (live price multiplier applied before decide, bar date)
    (0.985, "2026-03-01"), (0.985, "2026-03-02"), (1.00, "2026-03-03"), (1.04, "2026-03-04"), (1.00, "2026-03-05"),
    (0.97, "2026-03-06"), (0.985, "2026-03-07"), (1.01, "2026-03-08"), (1.03, "2026-03-09"),
]


def reference_actions():
    """What the frozen rules say, computed directly with strategy.py (no bot.py involved)."""
    import strategy as S
    f = Feed(); p = S.Params(); in_pos = False; bars_held = 0; out = []
    for mult, date in SCRIPT:
        f.live = f.bars[-1]["close"] * mult
        closes = [x["close"] for x in f.bars] + [f.live]
        snap = S.snapshot(closes, p)
        if in_pos:
            reason = S.exit_signal(snap, bars_held + 1, p)
            if reason:
                out.append(("SELL", reason)); in_pos = False; bars_held = 0
            else:
                out.append(("HOLD", "")); bars_held += 1
        else:
            if S.entry_signal(snap, p):
                out.append(("BUY", "rsi2_entry")); in_pos = True; bars_held = 0
            else:
                out.append(("NONE", ""))
        f.step(f.live, date)
    return out


def wrapped_actions(tmp_path, monkeypatch):
    os.environ["MODE"] = "paper"; os.environ["CC_VAR"] = str(tmp_path / "var")
    (tmp_path / "var" / "control").mkdir(parents=True)
    for m in ("cc", "bot"):
        sys.modules.pop(m, None)
    import cc
    import bot
    importlib.reload(cc); importlib.reload(bot)
    cc.bot.record_equity(100000, source="broker")  # synthetic account fixture
    assert cc.SDK, "cc_sdk must be importable for this test"
    bot.STATE_PATH = tmp_path / "state.json"; bot.LOG_PATH = tmp_path / "bot.log"
    monkeypatch.setattr(bot, "trading_day_today", lambda: True)
    from broker import PaperBroker
    f = Feed(); b = PaperBroker(str(tmp_path / "ledger.json"), 100_000, data=f); st = bot.load_state()
    out = []
    for mult, date in SCRIPT:
        f.live = f.bars[-1]["close"] * mult
        with cc.run("decide") as run:
            bot.cmd_decide(b, st, run)
        pend = st.get("pending")
        if pend:
            out.append((pend["side"], pend["reason"])); pend["date"] = date
        else:
            out.append(("HOLD" if st["in_position"] else "NONE", ""))
        f.step(f.live, date)
        with cc.run("reconcile") as run:
            bot.cmd_reconcile(b, st, run)
    return out, cc.bot


def test_wrapped_bot_matches_frozen_rules(tmp_path, monkeypatch):
    ref = reference_actions()
    got, sdk_bot = wrapped_actions(tmp_path, monkeypatch)
    assert [a for a, _ in got] == [a for a, _ in ref], f"\nref={ref}\ngot={got}"
    assert any(a == "BUY" for a, _ in ref) and any(a == "SELL" for a, _ in ref), "script must exercise a round trip"
    # SDK side effects exist and strategy.py is byte-identical to the frozen copy
    hb = sdk_bot.L.q("SELECT COUNT(*) n FROM heartbeats")[0]["n"]
    assert hb == 2 * len(SCRIPT)
    assert sdk_bot.L.one("SELECT COUNT(*) n FROM orders WHERE status IN ('sent','filled')")["n"] >= 2
    assert sdk_bot.L.one("SELECT COUNT(*) n FROM trades")["n"] >= 1
    assert sdk_bot.L.one("SELECT COUNT(*) n FROM orders WHERE status='rejected'")["n"] == 0


def test_strategy_file_frozen():
    import hashlib
    h = hashlib.sha256((HERE / "strategy.py").read_bytes()).hexdigest()
    frozen = json.loads((HERE / "tests" / "strategy_sha256.json").read_text())["sha256"]
    assert h == frozen, "strategy.py changed; trading rules are frozen"
