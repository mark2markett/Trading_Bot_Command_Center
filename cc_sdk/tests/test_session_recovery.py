"""Temporary data outages must not kill a paper session or conceal missing inputs."""
import json
from datetime import datetime, timedelta

import httpx
import pytest

from cc_sdk import Bot, BotManifest
from cc_sdk.intraday import ET, Bar, SessionRunner, Signal

DAY = datetime(2026, 10, 5, tzinfo=ET)


def make_bot(tmp_path):
    (tmp_path / "control").mkdir()
    return Bot(BotManifest("t_gap", "fixture", "0", "fixture", "SPY", "paper",
                           limits={"max_orders_per_day": 10}),
               db_path=tmp_path / "cc.db", control_dir=tmp_path / "control")


def daily_history(day):
    return [Bar(day - timedelta(days=i), 100, 101, 99, 100, 1000) for i in range(40, 0, -1)]


def mk_bars(day, closes):
    start = day.replace(hour=9, minute=30)
    return [Bar(start + timedelta(minutes=i), c, c + 0.2, c - 0.2, c, 1000) for i, c in enumerate(closes)]


class Feed:
    def __init__(self, error=None):
        self.error = error

    def daily_bars(self, symbol, n):
        return daily_history(DAY)

    def minute_bars(self, symbol, now):
        if symbol == "SPY" and self.error:
            raise self.error
        return mk_bars(DAY, [100.0] * 40)

    def quote(self, symbol):
        return 100.0, 0.0


class Rules:
    name = "fixture"

    def decide(self, bars, ctx):
        return Signal(1, "fixture", stop=99.0)


def http_error(status):
    request = httpx.Request("GET", "https://feed.test/bars?secret=must-not-log")
    response = httpx.Response(status, request=request)
    return httpx.HTTPStatusError("must-not-log", request=request, response=response)


@pytest.mark.parametrize("error", [http_error(500), http_error(429), httpx.ReadTimeout("must-not-log")])
def test_transient_bar_error_skips_symbol_and_recovers_on_next_poll(tmp_path, error):
    bot = make_bot(tmp_path)
    feed = Feed(error)
    runner = SessionRunner(bot, feed, Rules(), ["SPY", "QQQ"])
    runner.prepare(DAY)
    now = DAY.replace(hour=10, minute=15)
    runner.step(now)
    assert set(runner.open) == {"QQQ"}
    row = bot.L.one("SELECT signal_json, reason FROM decisions WHERE action='NO_DATA'")
    assert json.loads(row["signal_json"])["symbol"] == "SPY"
    assert "must-not-log" not in row["reason"]
    feed.error = None
    runner.step(now + timedelta(seconds=15))
    assert set(runner.open) == {"SPY", "QQQ"}


def test_permanent_auth_failure_is_not_swallowed(tmp_path):
    bot = make_bot(tmp_path)
    runner = SessionRunner(bot, Feed(http_error(401)), Rules(), ["SPY"])
    runner.prepare(DAY)
    with pytest.raises(httpx.HTTPStatusError):
        runner.step(DAY.replace(hour=10))


def test_no_signal_snapshot_is_recorded_at_most_once_per_five_minutes(tmp_path):
    bot = make_bot(tmp_path)
    rules = Rules()
    rules.decide = lambda bars, ctx: None
    runner = SessionRunner(bot, Feed(), rules, ["SPY"])
    runner.prepare(DAY)
    now = DAY.replace(hour=10)
    for seconds in (0, 15, 300):
        runner.step(now + timedelta(seconds=seconds))
    rows = bot.L.q("SELECT signal_json FROM decisions WHERE action='NO_SIGNAL'")
    assert len(rows) == 2
    signal = json.loads(rows[0]["signal_json"])
    assert signal["symbol"] == "SPY" and signal["bars"] > 0
    assert signal["context"]["prev_close"] == 100.0
    assert "last_bar" in signal


def test_lifecycle_log_survives_failure_without_open_file_handles(tmp_path):
    bot = make_bot(tmp_path)
    with pytest.raises(RuntimeError):
        with bot.run("session"):
            raise RuntimeError("fixture failure")
    path = bot.L.path.parent / "logs" / "t_gap.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert rows[0]["event"] == "run_started"
    assert rows[-1]["event"] == "run_failed" and rows[-1]["error_type"] == "RuntimeError"
    path.unlink()  # Windows cleanup must not encounter a lingering logging handle.


def test_unwritable_diagnostics_do_not_mask_failure_or_prevent_recovery(tmp_path, caplog):
    bot = make_bot(tmp_path)
    (tmp_path / "logs").write_text("occupied")
    with pytest.raises(RuntimeError, match="original failure"):
        with bot.run("session"):
            raise RuntimeError("original failure")
    assert bot.L.one("SELECT ok FROM heartbeats")["ok"] == 0
    assert bot.L.one("SELECT kind FROM alerts")["kind"] == "run_failed"
    runner = SessionRunner(bot, Feed(http_error(500)), Rules(), ["SPY"])
    runner.prepare(DAY)
    runner.step(DAY.replace(hour=10))
    assert not runner.open
    assert "diagnostic log unavailable" in caplog.text


def test_spread_recovers_then_closes_both_legs_at_eod(tmp_path):
    from test_options_runner import Feed as ChainFeed, Rules as SpreadRules, mk
    from cc_sdk.options_runner import SpreadSessionRunner
    class FlakyFeed(ChainFeed):
        failed = False
        def minute_bars(self, symbol, day):
            if not self.failed:
                self.failed = True
                raise http_error(500)
            return super().minute_bars(symbol, day)
    bot, _ = mk(tmp_path)
    feed = FlakyFeed()
    runner = SpreadSessionRunner(bot, feed, SpreadRules(), ["SPY"], adopt_positions=False)
    runner.prepare(DAY)
    runner.step(DAY.replace(hour=10, minute=1))
    assert not runner.open and not bot.positions()
    runner.step(DAY.replace(hour=10, minute=2))
    assert len(bot.positions()) == 2
    runner.step(DAY.replace(hour=15, minute=58))
    assert not runner.open and not bot.positions()
    assert bot.L.one("SELECT exit_reason FROM trades")["exit_reason"] == "eod"


def test_loop_heartbeat_marks_data_outage_then_recovers(tmp_path, monkeypatch):
    import cc_sdk.intraday as module
    bot = make_bot(tmp_path)
    feed = Feed(http_error(503))
    runner = SessionRunner(bot, feed, Rules(), ["SPY"])
    now = DAY.replace(hour=10)
    times = iter([now, now + timedelta(minutes=5), DAY.replace(hour=16)])
    class Clock:
        @staticmethod
        def now(tz):
            return next(times)
    monkeypatch.setattr(module, "datetime", Clock)
    clock = iter([1000.0, 1000.0, 1301.0, 1301.0])
    monkeypatch.setattr(module.time, "time", lambda: next(clock))
    def sleep(seconds):
        feed.error = None
        runner.open.clear()
        runner.rules.decide = lambda bars, ctx: None
    monkeypatch.setattr(module.time, "sleep", sleep)
    runner.loop(DAY)
    rows = bot.L.q("SELECT ok,detail FROM heartbeats ORDER BY id")
    assert [r["ok"] for r in rows] == [0, 1]
    assert "SPY" in json.loads(rows[0]["detail"])["data_errors"]
