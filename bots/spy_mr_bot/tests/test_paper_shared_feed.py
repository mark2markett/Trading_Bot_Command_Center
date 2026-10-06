"""Paper mode uses the fleet's data-only session, never a legacy trading client."""
import importlib.util
from datetime import datetime
from pathlib import Path

import pytest

from cc_sdk.intraday import Bar, ET


class Feed:
    def daily_bars(self, symbol, n):
        return [Bar(datetime(2026, 10, 5, tzinfo=ET), 770, 775, 769, 774, 1000)]

    def quote(self, symbol):
        return 774.0, 1.0


@pytest.fixture
def bot(tmp_path, monkeypatch):
    source = Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(source))
    monkeypatch.setenv("CC_VAR", str(tmp_path / "var"))
    monkeypatch.setenv("MODE", "paper")
    (tmp_path / "var/control").mkdir(parents=True)
    (tmp_path / "bot.py").write_bytes((source / "bot.py").read_bytes())
    spec = importlib.util.spec_from_file_location("paper_feed_subject", tmp_path / "bot.py")
    subject = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(subject)
    return subject


def test_paper_uses_shared_data_without_legacy_auth(bot, tmp_path, monkeypatch):
    from cc_sdk.schwab_feed import SchwabFeed, SHARED_VARS
    monkeypatch.setattr(bot, "MODE", "paper")
    monkeypatch.setattr(bot, "HERE", tmp_path)
    monkeypatch.setattr(bot, "load_dotenv", lambda *a, **kw: None)
    for key in SHARED_VARS:
        monkeypatch.setenv(key, "fixture")
    for key in ("SCHWAB_API_KEY", "SCHWAB_APP_SECRET", "SCHWAB_CALLBACK_URL"):
        monkeypatch.setenv(key, "legacy")
    monkeypatch.setattr(SchwabFeed, "connect", lambda directory: Feed())
    monkeypatch.setattr(bot, "SchwabBroker", lambda *a, **kw: pytest.fail("legacy OAuth/trader client accessed"))
    broker = bot.make_broker()
    assert broker.last_price("SPY") == 774.0
    assert broker.daily_closes("SPY")[0] == {"date": "2026-10-05", "open": 770, "high": 775, "low": 769, "close": 774}


def test_configured_shared_data_failure_does_not_silently_use_eod_data(bot, tmp_path, monkeypatch):
    from cc_sdk.schwab_feed import SchwabFeed, SHARED_VARS
    monkeypatch.setattr(bot, "MODE", "paper")
    monkeypatch.setattr(bot, "HERE", tmp_path)
    monkeypatch.setattr(bot, "load_dotenv", lambda *a, **kw: None)
    for key in SHARED_VARS:
        monkeypatch.setenv(key, "fixture")
    def fail(directory):
        raise RuntimeError("shared data unavailable")
    monkeypatch.setattr(SchwabFeed, "connect", fail)
    with pytest.raises(RuntimeError, match="shared data unavailable"):
        bot.make_broker()


def clear_config(monkeypatch):
    from cc_sdk.schwab_feed import SHARED_VARS
    for key in (*SHARED_VARS, "CC_TOKEN_BROKER_URL", "CC_TOKEN_BROKER_SECRET"):
        monkeypatch.delenv(key, raising=False)


def test_partial_shared_configuration_surfaces_error(bot, monkeypatch):
    clear_config(monkeypatch)
    monkeypatch.setattr(bot, "load_dotenv", lambda *a, **kw: None)
    monkeypatch.setenv("CC_TOKEN_BROKER_URL", "https://fixture.test")
    with pytest.raises(RuntimeError, match="incomplete"):
        bot.make_broker()


def test_unconfigured_standalone_paper_does_not_require_sdk(bot, monkeypatch):
    import builtins
    clear_config(monkeypatch)
    monkeypatch.setattr(bot, "load_dotenv", lambda *a, **kw: None)
    original = builtins.__import__
    def no_sdk(name, *args, **kwargs):
        if name.startswith("cc_sdk"):
            raise ModuleNotFoundError(name)
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", no_sdk)
    assert bot.make_broker().data is None


def test_shared_daily_data_excludes_unfinished_bar_at_morning_reconcile(monkeypatch):
    import broker
    class Clock:
        @staticmethod
        def now(tz):
            return datetime(2026, 10, 6, 9, 45, tzinfo=ET)
    monkeypatch.setattr(broker, "datetime", Clock)
    feed = Feed()
    previous = feed.daily_bars("SPY", 5)[0]
    feed.daily_bars = lambda symbol, n: [previous, Bar(datetime(2026, 10, 6, tzinfo=ET), 775, 776, 774, 775, 1000)]
    assert [r["date"] for r in broker.SharedSchwabData(feed).daily_closes("SPY", 5)] == ["2026-10-05"]


def test_stale_shared_quote_is_refused():
    import broker
    feed = Feed()
    feed.quote = lambda symbol: (774.0, 91.0)
    with pytest.raises(broker.BrokerError, match="90-second"):
        broker.SharedSchwabData(feed).last_price("SPY")
