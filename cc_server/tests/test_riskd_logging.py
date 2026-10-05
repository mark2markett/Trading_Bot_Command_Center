"""A failed risk-monitor tick retains the exception's source traceback."""
import asyncio
import logging
import sqlite3

from cc_sdk.ledger import Ledger
from cc_server import api, main


def test_riskd_failure_records_traceback(tmp_path, monkeypatch, caplog):
    ledger = Ledger(tmp_path / "fixture.db")
    monkeypatch.setattr(api, "_L", ledger)
    monkeypatch.setattr(main, "Alerter", lambda ledger: None)
    async def exercise():
        loop = asyncio.get_running_loop()
        stop = asyncio.Event()
        def failed_tick(ledger, alerter):
            loop.call_soon_threadsafe(stop.set)
            raise sqlite3.ProgrammingError("fixture SQLite failure")
        monkeypatch.setattr(main.riskd, "tick", failed_tick)
        await main.riskd_loop(stop)
    try:
        with caplog.at_level(logging.ERROR, logger="riskd"):
            asyncio.run(exercise())
        records = [record for record in caplog.records if record.name == "riskd"]
        assert len(records) == 1
        assert records[0].exc_info is not None, "Risk failure lost its source traceback"
        assert "fixture SQLite failure" in caplog.text
    finally:
        ledger.conn.close()
