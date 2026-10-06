from datetime import timedelta
from cc_sdk.ledger import now
from cc_sdk.paper_account import configure, mark, record, snapshot
from cc_server import riskd


import pytest
from cc_sdk import Bot, BotManifest, Order


def fleet(tmp_path):
    (tmp_path / "control").mkdir()
    bots = [
        Bot(
            BotManifest(id=name, name=name, version="1", strategy_line="x", instrument="SPY", mode="paper"),
            db_path=tmp_path / "cc.db",
            control_dir=tmp_path / "control",
        )
        for name in ("bot_a", "bot_b")
    ]
    return bots


def test_paper_drawdown_and_exposure_use_shared_marked_equity(tmp_path):
    a, _ = fleet(tmp_path)
    configure(a.L, 100000)
    a.set_position("SPY", 100, 500, "x", 0)
    mark(a.L, "SPY", 400, now())
    record(a.L)
    assert riskd.portfolio_drawdown(a.L) == {"dd": 0.1, "equity": 90000.0, "peak": 100000.0, "source": "paper"}
    assert riskd.gross_exposure(a.L)["usd"] == 40000
    mark(a.L, "SPY", 400, now() - timedelta(seconds=91))
    assert riskd.portfolio_drawdown(a.L)["equity"] is None


def test_risk_tick_refreshes_open_paper_marks_and_captures_history(tmp_path, monkeypatch):
    a, _ = fleet(tmp_path)
    configure(a.L, 100000)
    a.set_position("SPY", 10, 500, "x", 0)

    class Feed:
        def account_quote(self, symbol):
            return 510, 2

    monkeypatch.setattr(riskd, "paper_feed", lambda: Feed())
    monkeypatch.setenv("CC_VAR", str(tmp_path))
    riskd.tick(a.L)
    assert snapshot(a.L)["equity"] == 100100
    assert a.L.one("SELECT equity FROM paper_equity ORDER BY id DESC LIMIT 1")["equity"] == 100100


def test_readiness_endpoint_is_read_only(tmp_path, monkeypatch):
    import sqlite3
    from fastapi.testclient import TestClient
    from cc_server import api, main

    a, _ = fleet(tmp_path)
    configure(a.L, 100000)
    monkeypatch.setattr(api, "L", lambda: a.L)
    blocked = {sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE}
    a.L.conn.set_authorizer(lambda action, *rest: sqlite3.SQLITE_DENY if action in blocked else sqlite3.SQLITE_OK)
    try:
        response = TestClient(main.app).get("/api/readiness")
        assert response.status_code == 200
        assert response.json()["paper_account"]["equity"] == 100000
        assert response.json()["paper_account"]["source"] == "paper"
    finally:
        a.L.conn.set_authorizer(None)
