"""Read-only native evidence: online ledger backup, API state, scanner probe.

Writes only to the supplied review directory. Never instantiate a bot, register a
manifest, place an order, change controls, or export environment/credential files.
"""
import importlib.util
import json
import math
import os
import sqlite3
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.dont_write_bytecode = True


def save(path, data):
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def backup(source, target):
    started = time.monotonic()

    def progress(status, remaining, total):
        if time.monotonic() - started > 20:
            raise TimeoutError("online backup deadline")

    with sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True, timeout=5) as src:
        with sqlite3.connect(target) as dst:
            src.backup(dst, pages=256, progress=progress)
            if dst.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise RuntimeError("backup integrity check failed")


def main(root, review):
    root, review = Path(root).resolve(), Path(review).resolve()
    # /bots and /fleet recompute parity and WRITE kv/alerts. Never request
    # those endpoints from an evidence collector; bot state comes from backup.
    for endpoint in ("health", "risk", "alerts", "research"):
        try:
            with urllib.request.urlopen("http://127.0.0.1:8585/api/" + endpoint, timeout=10) as response:
                data = json.load(response)
            save(review / (endpoint + ".json"), data)
        except Exception as error:
            save(review / (endpoint + "-status.json"), {"responding": False, "error_type": type(error).__name__})
    runtime = Path(os.environ.get("CC_VAR", str(root / "var"))).resolve()
    backup(runtime / "cc.db", review / "ledger.db")
    with sqlite3.connect((review / "ledger.db").as_uri() + "?mode=ro", uri=True) as ledger:
        ledger.row_factory = sqlite3.Row
        bots = []
        for bot in ledger.execute("SELECT id,name,mode,status FROM bots ORDER BY id").fetchall():
            row = dict(bot)
            heartbeat = ledger.execute("SELECT run,at,ok,detail FROM heartbeats WHERE bot_id=? ORDER BY id DESC LIMIT 1", (row["id"],)).fetchone()
            row["heartbeat"] = dict(heartbeat) if heartbeat else None
            row["positions"] = [dict(p) for p in ledger.execute("SELECT symbol,qty,avg_price FROM positions WHERE bot_id=?", (row["id"],))]
            bots.append(row)
        save(review / "bots.json", {"source": "read-only backup; stored status, no watchdog/parity recomputation", "bots": bots})
        equity = ledger.execute("SELECT at,equity FROM equity WHERE source='broker' ORDER BY at DESC,id DESC LIMIT 1").fetchone()
        value = equity[1] if equity else None
        save(review / "fleet-readiness.json", {
            "account_equity_present": equity is not None,
            "account_equity_valid": isinstance(value, (int, float)) and math.isfinite(value) and value > 0,
            "account_equity": value,
            "account_equity_at": equity[0] if equity else None,
            "warning": None if equity else "Fleet gross-exposure/drawdown protection has no account equity basis.",
        })
    # Match the SIP command's env order: existing process, .env defaults,
    # then .env.local overrides. Values remain in-process only.
    from dotenv import load_dotenv
    bot_dir = root / "bots" / "sip_orb"
    load_dotenv(bot_dir / ".env")
    load_dotenv(bot_dir / ".env.local", override=True)
    url = os.getenv("SCANNER_URL", "").strip()
    result = {
        "scanner_url_present": bool(url),
        "scanner_secret_configured": len(os.getenv("SCANNER_SECRET", "")) >= 32,
        "fallback_configured": bool(os.getenv("SIP_SYMBOLS", "").strip()),
    }
    client = bot_dir / "sip_scanner.py"
    if url and result["scanner_secret_configured"] and client.is_file():
        sys.path.insert(0, str(root / "cc_sdk"))
        try:
            spec = importlib.util.spec_from_file_location("native_review_sip", client)
            scanner = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(scanner)
            payload = scanner.fetch(url, timeout=10)
            now = datetime.now(ZoneInfo("America/New_York"))
            result.update({"endpoint_ready": True, "checked_at": now.isoformat(),
                           "version": payload.get("version"), "session_date": payload.get("session_date"),
                           "generated_at": payload.get("generated_at"), "coverage": payload.get("coverage")})
            try:
                result["fresh_selected_symbols"] = scanner.parse_snapshot(payload, now)
                result["valid_and_fresh_now"] = True
            except Exception:
                result["valid_and_fresh_now"] = False
                result["note"] = "Snapshot is stale or invalid at collection time; late-day staleness is expected. Review morning SCANNER decisions separately."
        except Exception as error:
            result.update({"endpoint_ready": False, "error_type": type(error).__name__})
    else:
        result["probe_performed"] = False
    save(review / "scanner-status.json", result)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
