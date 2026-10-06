"""Scanner responses must prove the current completed window, without blocking exits."""

import importlib.util
import json
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import pytest
from cc_sdk.intraday import ET, SessionRunner, UniversePending
from test_session_recovery import make_bot, Feed, Rules, DAY

spec = importlib.util.spec_from_file_location("sip_subject", Path(__file__).resolve().parents[2] / "bots/sip_orb/sip_scanner.py")
scanner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scanner)
NOW = datetime(2026, 10, 6, 9, 35, tzinfo=ET)


def snapshot():
    return {
        "version": 1,
        "status": "ready",
        "session_date": "2026-10-06",
        "generated_at": NOW.isoformat(),
        "window_start": NOW.replace(minute=30).isoformat(),
        "window_end": NOW.isoformat(),
        "coverage": {"universe": 1, "eligible": 1, "observed": 1, "excluded": 0},
        "exclusions": [],
        "candidates": [{"symbol": "NVDA", "price": 10, "rvol": 2, "atr14": 1, "avg_vol": 1000000}],
    }


@pytest.mark.parametrize(
    "key,value",
    [
        ("version", 2),
        ("session_date", "2026-10-05"),
        ("window_end", NOW.replace(minute=34).isoformat()),
        ("generated_at", (NOW - timedelta(minutes=6)).isoformat()),
        ("generated_at", (NOW + timedelta(minutes=1)).isoformat()),
        ("generated_at", NOW.replace(minute=34).isoformat()),
    ],
)
def test_rejects_wrong_session_window_version_or_staleness(key, value):
    data = snapshot()
    data[key] = value
    with pytest.raises(RuntimeError):
        scanner.parse_snapshot(data, NOW)


@pytest.mark.parametrize(
    "change", [{"price": float("nan")}, {"rvol": float("inf")}, {"avg_vol": True}, {"symbol": "https://bad"}]
)
def test_invalid_candidates_are_errors_not_silent_empty(change):
    data = snapshot()
    data["candidates"][0].update(change)
    with pytest.raises(RuntimeError):
        scanner.parse_snapshot(data, NOW)


def test_ready_empty_and_alphabetic_ties_are_valid():
    data = snapshot()
    data["candidates"] = []
    assert scanner.parse_snapshot(data, NOW) == []
    data = snapshot()
    data["candidates"].append({**data["candidates"][0], "symbol": "AMD"})
    data["coverage"] = {"universe": 2, "eligible": 2, "observed": 2, "excluded": 0}
    assert scanner.parse_snapshot(data, NOW) == ["AMD", "NVDA"]


@pytest.mark.parametrize("status", [202, 429, 500, 503])
def test_http_pending_is_retryable_authenticated_and_never_follows_redirects(monkeypatch, status):
    monkeypatch.setenv("SCANNER_SECRET", "s" * 32)

    def get(url, **kwargs):
        assert kwargs["headers"]["Authorization"] == "Bearer " + "s" * 32
        assert kwargs["follow_redirects"] is False
        return httpx.Response(status, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", get)
    with pytest.raises(UniversePending):
        scanner.fetch("https://scanner.test")


def test_pending_universe_does_not_block_stop_exits_then_recovers(tmp_path):
    bot = make_bot(tmp_path)
    feed = Feed()
    runner = SessionRunner(bot, feed, Rules(), ["SPY"])
    runner.prepare(DAY)
    runner.step(DAY.replace(hour=10))
    assert runner.open

    def pending(now):
        raise UniversePending("SCANNER_PENDING")

    runner.universe_fn = pending
    runner.universe_done = False
    runner.symbols = []
    feed.quote = lambda symbol: (98.0, 0)
    runner.step(DAY.replace(hour=9, minute=35))
    assert not runner.open and not runner.universe_done
    assert runner._poll_errors["scanner"]
    runner.universe_fn = lambda now: []
    runner.step(DAY.replace(hour=9, minute=36))
    assert runner.universe_done and not runner._poll_errors


def test_deadline_persists_failure_while_session_keeps_running(tmp_path):
    bot = make_bot(tmp_path)
    calls = []

    def pending(now):
        calls.append(now)
        raise UniversePending("SCANNER_PENDING")

    runner = SessionRunner(bot, Feed(), Rules(), [], universe_fn=pending)
    runner.step(DAY.replace(hour=9, minute=35))
    runner.step(DAY.replace(hour=9, minute=40))
    runner.step(DAY.replace(hour=10))
    assert len(calls) == 1 and runner.universe_done and not runner.symbols
    assert "scanner" in runner._poll_errors
    assert bot.L.one("SELECT reason FROM decisions WHERE action='SCANNER_UNAVAILABLE'")


def test_actual_platform_snapshot_runs_sip_signal_risk_paper_fill_and_eod_exit(tmp_path, monkeypatch):
    from cc_sdk.intraday import Bar

    rules_spec = importlib.util.spec_from_file_location(
        "sip_rules_subject", Path(__file__).resolve().parents[2] / "bots/sip_orb/sip_orb_rules.py"
    )
    rules_module = importlib.util.module_from_spec(rules_spec)
    rules_spec.loader.exec_module(rules_module)
    payload = json.loads((Path(__file__).parent / "fixtures/sip-v1-ready.json").read_text())
    monkeypatch.setenv("SCANNER_URL", "https://scanner.test")
    monkeypatch.setenv("SCANNER_SECRET", "s" * 32)
    monkeypatch.delenv("SIP_SYMBOLS", raising=False)
    monkeypatch.setattr(httpx, "get", lambda url, **kwargs: httpx.Response(200, json=payload, request=httpx.Request("GET", url)))
    feed = Feed()

    def minutes(symbol, day):
        return [
            Bar(NOW.replace(minute=30) + timedelta(minutes=i), 100, 101 + i * 0.1, 99, 100 + i * 0.1, 1000) for i in range(5)
        ] + [Bar(NOW, 100.4, 102, 100, 101.9, 1000)]

    feed.minute_bars = minutes
    feed.quote = lambda symbol: (101.9, 0)
    bot = make_bot(tmp_path)
    runner = SessionRunner(bot, feed, rules_module.SipOrbRules(), [], universe_fn=scanner.universe, adopt_positions=False, risk_pct=0.001)
    runner.prepare(NOW)
    runner.step(NOW + timedelta(minutes=1))
    assert set(runner.open) == {"AMD", "NVDA"}
    assert len(bot.L.q("SELECT id FROM fills")) == 2
    runner.step(NOW.replace(hour=15, minute=58))
    assert not runner.open and not bot.positions()
    trades = bot.L.q("SELECT exit_reason FROM trades")
    assert len(trades) == 2 and all(t["exit_reason"] == "eod" for t in trades)
    assert len(bot.L.q("SELECT id FROM fills")) == 4


@pytest.mark.parametrize("control", ["entries_paused", "kill", "flatten"])
def test_scanner_deadline_evidence_survives_entry_control_early_returns(tmp_path, monkeypatch, control):
    bot = make_bot(tmp_path)

    def pending(now):
        raise UniversePending("SCANNER_PENDING")

    runner = SessionRunner(bot, Feed(), Rules(), [], universe_fn=pending)
    runner.step(DAY.replace(hour=9, minute=35))
    attribute = {"entries_paused": "entries_paused", "kill": "killed", "flatten": "flatten_requested"}[control]
    monkeypatch.setattr(bot.control, attribute, lambda: True)
    runner.step(DAY.replace(hour=9, minute=40))
    runner.step(DAY.replace(hour=10))
    assert runner.universe_done and runner._universe_failure
    assert "scanner" in runner._poll_errors
    assert bot.L.one("SELECT id FROM decisions WHERE action='SCANNER_UNAVAILABLE'")


def test_candidate_count_cannot_exceed_observed_coverage():
    data = snapshot()
    data['coverage'] = {'universe': 0, 'eligible': 0, 'observed': 0, 'excluded': 0}
    with pytest.raises(RuntimeError):
        scanner.parse_snapshot(data, NOW)
