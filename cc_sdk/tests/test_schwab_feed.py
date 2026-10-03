"""Regression for M6.7: a module-level helper was inserted mid-class in schwab_feed.py, so every method after it
(check, _bars, minute_bars, quote, daily_bars) became a nested local function and `bot.py auth/check/session`
crashed with AttributeError. These tests pin the class surface and exercise check() against a fake client
(no network, no schwab-py)."""
from datetime import datetime

from cc_sdk import schwab_feed
from cc_sdk.intraday import ET
from cc_sdk.schwab_feed import SchwabFeed

METHODS = ("check", "_bars", "minute_bars", "quote", "daily_bars")


def test_methods_attach_to_class():
    for name in METHODS:
        assert callable(getattr(SchwabFeed, name, None)), f"SchwabFeed.{name} missing — a module-level def slipped into the class body"
    assert callable(schwab_feed.write_issued_sidecar)
    assert not hasattr(SchwabFeed, "write_issued_sidecar")


class _Resp:
    def __init__(self, payload):
        self._p = payload
        self.status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return self._p


class _FakeClient:
    """Mimics the two schwab-py calls check() makes. Minute bars are one 09:30 and one 09:31 candle today."""

    def get_quote(self, symbol):
        return _Resp({symbol: {"quote": {"lastPrice": 567.89, "quoteTime": 0}}})

    def get_price_history_every_minute(self, symbol, start_datetime, end_datetime, need_extended_hours_data):
        base = start_datetime.replace(hour=9, minute=30, second=0, microsecond=0)
        candles = []
        for i in range(2):
            t = base.replace(minute=30 + i)
            candles.append({"datetime": int(t.timestamp() * 1000), "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 100})
        return _Resp({"candles": candles})


def test_check_runs_end_to_end(monkeypatch, tmp_path):
    monkeypatch.setattr(schwab_feed, "token_path", lambda bot_dir=None: tmp_path / "schwab_token.json")
    out = SchwabFeed(_FakeClient()).check("SPY")
    assert out["symbol"] == "SPY"
    assert out["last"] == 567.89
    assert out["minute_bars_today"] == 2
    assert out["token_file"].endswith("schwab_token.json")
    assert "refresh" not in str(out).lower()  # never leaks token material


def test_minute_bars_filters_to_regular_hours():
    feed = SchwabFeed(_FakeClient())
    bars = feed.minute_bars("SPY", datetime.now(ET))
    assert [b.mod for b in bars] == [570, 571]
