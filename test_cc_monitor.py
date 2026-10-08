import importlib.util
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

spec = importlib.util.spec_from_file_location("cc_monitor", Path(__file__).with_name("CC-MONITOR.py"))
monitor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(monitor)
ET = ZoneInfo("America/New_York")
NOW = datetime(2026, 10, 8, 10, 0, tzinfo=ET)


def state():
    health = {"ok": True, "riskd_last": {"at": NOW.isoformat()}}
    readiness = {"paper_account": {"ready": True}, "paper_fleet": True, "bot_count": 5,
                 "bot_ids": sorted(monitor.BOT_IDS), "killed": False, "entries_paused": False}
    bots = [{"id": bot, "mode": "paper", "status": "running", "positions": [],
             "heartbeat": {"at": NOW.isoformat(), "ok": 1},
             "scheduled_heartbeats": {"reconcile": {"at": NOW.isoformat(), "ok": 1}}}
            for bot in sorted(monitor.BOT_IDS)]
    return health, readiness, bots


def assess(bots=None, scanner="UNIVERSE", active=True):
    health, readiness, registered = state()
    return monitor.assess(health, readiness, bots or registered, scanner, NOW, active)


def test_healthy_fleet_with_valid_empty_universe_passes():
    assert assess()["ok"] is True


def test_stale_intraday_heartbeat_fails_without_treating_daily_bot_as_continuous():
    _, _, bots = state()
    for bot in bots:
        if bot["id"] in ("gap_go", "spy_mr"):
            bot["heartbeat"]["at"] = (NOW - timedelta(minutes=11)).isoformat()
    result = assess(bots)
    assert result["checks"]["gap_go_heartbeat"] is False
    assert "spy_mr_heartbeat" not in result["checks"]


@pytest.mark.parametrize("scanner", [None, "SCANNER_UNAVAILABLE"])
def test_missing_or_failed_opening_universe_is_not_ready(scanner):
    assert assess(scanner=scanner)["checks"]["sip_opening_universe"] is False


def test_closed_market_does_not_require_fresh_intraday_heartbeats():
    _, _, bots = state()
    for bot in bots:
        bot["heartbeat"]["at"] = (NOW - timedelta(days=1)).isoformat()
    result = assess(bots, scanner=None, active=False)
    assert result["ok"] is True
    assert "sip_opening_universe" not in result["checks"]


def test_failed_heartbeat_and_pause_are_reported_without_mutating_controls():
    health, readiness, bots = state()
    bots[0]["heartbeat"]["ok"] = 0
    readiness["entries_paused"] = True
    result = monitor.assess(health, readiness, bots, "UNIVERSE", NOW, True)
    assert result["ok"] is False
    assert readiness["entries_paused"] is True


def test_ledger_read_ignores_yesterdays_universe_and_never_writes(tmp_path):
    path = tmp_path / "ledger.db"
    with sqlite3.connect(path) as db:
        db.executescript('''
            CREATE TABLE bots(id TEXT,mode TEXT,status TEXT);
            CREATE TABLE heartbeats(id INTEGER PRIMARY KEY,bot_id TEXT,run TEXT,at TEXT,ok INTEGER);
            CREATE TABLE positions(bot_id TEXT,symbol TEXT,qty REAL);
            CREATE TABLE decisions(id INTEGER PRIMARY KEY,bot_id TEXT,at TEXT,action TEXT);
        ''')
        db.execute("INSERT INTO bots VALUES('sip_orb','paper','running')")
        db.execute("INSERT INTO heartbeats VALUES(1,'sip_orb','session',?,1)", (NOW.isoformat(),))
        db.execute("INSERT INTO decisions VALUES(1,'sip_orb',?,'UNIVERSE')", ((NOW-timedelta(days=1)).isoformat(),))
        db.execute("INSERT INTO decisions VALUES(2,'sip_orb',?,'SCANNER_UNAVAILABLE')", (NOW.isoformat(),))
    before = path.read_bytes()
    bots, scanner = monitor.read_ledger(path, NOW)
    assert bots[0]["heartbeat"]["ok"] == 1
    assert scanner == "SCANNER_UNAVAILABLE"
    assert path.read_bytes() == before


def test_missing_ledger_is_not_created(tmp_path):
    path = tmp_path / "missing.db"
    with pytest.raises(sqlite3.OperationalError):
        monitor.read_ledger(path, NOW)
    assert not path.exists()


def test_daily_reconcile_failure_after_grace_is_detected():
    _, _, bots = state()
    next(b for b in bots if b["id"] == "spy_mr")["scheduled_heartbeats"]["reconcile"]["ok"] = 0
    assert assess(bots)["checks"]["spy_mr_reconcile"] is False


def test_daily_decide_is_checked_after_close_without_continuous_intraday_heartbeat_requirement():
    health, readiness, bots = state()
    now = NOW.replace(hour=16, minute=5)
    health["riskd_last"]["at"] = now.isoformat()
    result = monitor.assess(health, readiness, bots, None, now, False, trading_day=True)
    assert result["checks"]["spy_mr_decide"] is False
    assert "gap_go_heartbeat" not in result["checks"]


def test_intraday_position_left_open_after_close_is_flagged_but_daily_position_is_allowed():
    health, readiness, bots = state()
    now = NOW.replace(hour=16, minute=15)
    health["riskd_last"]["at"] = now.isoformat()
    daily = next(b for b in bots if b["id"] == "spy_mr")
    daily["scheduled_heartbeats"]["decide"] = {"at": now.isoformat(), "ok": 1}
    daily["positions"] = [{"symbol": "SPY", "qty": 100}]
    intraday = next(b for b in bots if b["id"] == "nr7")
    intraday["positions"] = [{"symbol": "SPY", "qty": -32}]
    assert monitor.assess(health, readiness, bots, None, now, False, trading_day=True)["checks"]["intraday_flat_after_close"] is False
    intraday["positions"] = []
    assert monitor.assess(health, readiness, bots, None, now, False, trading_day=True)["checks"]["intraday_flat_after_close"] is True
