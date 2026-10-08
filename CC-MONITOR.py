"""Bounded native observations. Reads APIs/SQLite; writes only monitor reports.

No vendor credential reads, orders, controls, bot launches or ledger writes.
The Windows wrapper separately starts an enabled, stopped CC server at most
once per 30 minutes. These observations do not certify live quote freshness.
"""
import argparse
import importlib.util
import json
import os
import sqlite3
import urllib.error
import urllib.request
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
BOT_IDS = {"gap_go", "gap_go_spread", "nr7", "sip_orb", "spy_mr"}
INTRADAY_IDS = BOT_IDS - {"spy_mr"}


def read_ledger(path, current):
    start = current.astimezone(ET).replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    bounds = (start.astimezone(timezone.utc).isoformat(), end.astimezone(timezone.utc).isoformat())
    with closing(sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True, timeout=3)) as db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN")
        bots = []
        for row in db.execute("SELECT id,mode,status FROM bots ORDER BY id").fetchall():
            bot = dict(row)
            heartbeat = db.execute("SELECT run,at,ok FROM heartbeats WHERE bot_id=? ORDER BY id DESC LIMIT 1", (row["id"],)).fetchone()
            bot["heartbeat"] = dict(heartbeat) if heartbeat else None
            bot["positions"] = [dict(p) for p in db.execute("SELECT symbol,qty FROM positions WHERE bot_id=? AND qty<>0", (row["id"],))]
            if row["id"] == "spy_mr":
                bot["scheduled_heartbeats"] = {}
                for run in ("reconcile", "decide"):
                    hb = db.execute("SELECT at,ok FROM heartbeats WHERE bot_id=? AND run=? AND at>=? AND at<? ORDER BY id DESC LIMIT 1",
                                    (row["id"], run, *bounds)).fetchone()
                    bot["scheduled_heartbeats"][run] = dict(hb) if hb else None
            bots.append(bot)
        scanner = db.execute("SELECT action FROM decisions WHERE bot_id='sip_orb' AND at>=? AND at<? "
                             "AND action IN ('UNIVERSE','SCANNER_UNAVAILABLE') ORDER BY id DESC LIMIT 1", bounds).fetchone()
        return bots, scanner["action"] if scanner else None


def assess(health, readiness, bots, scanner, current, active, trading_day=None, close_min=960):
    current = current.astimezone(ET)
    checks = {}
    try:
        lag = (current - datetime.fromisoformat(health["riskd_last"]["at"].replace("Z", "+00:00"))).total_seconds()
        checks["server_riskd"] = health.get("ok") is True and -30 <= lag <= 90
    except (KeyError, TypeError, ValueError):
        checks["server_riskd"] = False
    account = readiness.get("paper_account")
    checks["shared_paper_valuation"] = isinstance(account, dict) and account.get("ready") is True
    checks["five_paper_bots"] = (readiness.get("paper_fleet") is True and readiness.get("bot_count") == 5
                                 and isinstance(readiness.get("bot_ids"), list) and set(readiness["bot_ids"]) == BOT_IDS
                                 and {b["id"] for b in bots} == BOT_IDS and all(b["mode"] == "paper" for b in bots))
    checks["fleet_controls_allow_entries"] = readiness.get("killed") is False and readiness.get("entries_paused") is False
    if active:
        for bot_id in sorted(INTRADAY_IDS):
            bot = next((b for b in bots if b["id"] == bot_id), {})
            hb = bot.get("heartbeat") or {}
            try:
                lag = (current - datetime.fromisoformat(hb["at"].replace("Z", "+00:00"))).total_seconds()
                checks[bot_id + "_heartbeat"] = hb.get("ok") == 1 and -30 <= lag <= 600
            except (KeyError, TypeError, ValueError):
                checks[bot_id + "_heartbeat"] = False
            checks[bot_id + "_status"] = bot.get("status") == "running"
        if current.hour * 60 + current.minute >= 580:
            checks["sip_opening_universe"] = scanner == "UNIVERSE"
    is_trading_day = active if trading_day is None else trading_day
    if is_trading_day:
        daily = next((b for b in bots if b["id"] == "spy_mr"), {})
        for run, minute in (("reconcile", 585), ("decide", close_min - 10)):
            due = current.replace(hour=minute // 60, minute=minute % 60, second=0, microsecond=0)
            if current < due + timedelta(minutes=10):
                continue
            hb = daily.get("scheduled_heartbeats", {}).get(run) or {}
            try:
                at = datetime.fromisoformat(hb["at"].replace("Z", "+00:00"))
                checks["spy_mr_" + run] = hb.get("ok") == 1 and due <= at <= current + timedelta(seconds=30)
            except (KeyError, TypeError, ValueError):
                checks["spy_mr_" + run] = False
        if current.hour * 60 + current.minute >= close_min + 10:
            checks["intraday_flat_after_close"] = not any(b.get("positions") for b in bots if b["id"] in INTRADAY_IDS)
    return {"ok": all(checks.values()), "checks": checks, "market_monitoring_window": active,
            "bots": bots, "sip_opening_result": scanner,
            "scope": "Stored runtime evidence; no fresh vendor quote or authenticated scanner probe."}


def fetch_json(url):
    request = urllib.request.Request(url, headers={"User-Agent": "CC-native-health-monitor/1.0"})
    try:
        response = urllib.request.urlopen(request, timeout=10)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        return response.status, json.load(response)


def capture(root):
    current = datetime.now(ET)
    errors = []
    payloads = {}
    for endpoint in ("health", "readiness"):
        try:
            status, data = fetch_json("http://127.0.0.1:8585/api/" + endpoint)
            if status != 200 or not isinstance(data, dict):
                raise ValueError("Unexpected API response")
            payloads[endpoint] = data
        except Exception as error:  # noqa: BLE001 — failed observations must not stop the remaining checks
            errors.append(endpoint + ":" + type(error).__name__)
            payloads[endpoint] = {}
    active, trading_day, close = False, False, 960
    try:
        calendar_path = root / "cc_server" / "cc_server" / "calendar.py"
        spec = importlib.util.spec_from_file_location("cc_monitor_calendar", calendar_path)
        calendar = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(calendar)
        if not 2025 <= current.year <= 2027:
            raise ValueError("Calendar coverage unavailable")
        close = 780 if calendar.is_early_close(current.date()) else 960
        trading_day = calendar.is_trading_day(current.date())
        active = trading_day and 575 <= current.hour * 60 + current.minute < close
    except Exception as error:  # noqa: BLE001 — calendar failure is explicitly reported, never passed
        errors.append("calendar:" + type(error).__name__)
    try:
        default_db = Path(os.environ.get("CC_VAR", str(root / "var"))) / "cc.db"
        db_path = payloads["health"].get("db") or str(default_db)
        bots, scanner = read_ledger(db_path, current)
    except Exception as error:  # noqa: BLE001 — retain the failure without creating a replacement ledger
        errors.append("ledger:" + type(error).__name__)
        bots, scanner = [], None
    result = assess(payloads["health"], payloads["readiness"], bots, scanner, current, active, trading_day, close)
    account = payloads["readiness"].get("paper_account")
    if isinstance(account, dict):
        result["paper_account"] = {key: account[key] for key in ("ready", "equity", "reason", "missing_marks", "stale_marks") if key in account}
    try:
        status, data = fetch_json("https://www.mark2markets.com/api/healthcheck")
        result["platform"] = {"http_status": status, "ok": data.get("ok"),
                              "checks": {key: value for key, value in data.get("checks", {}).items() if isinstance(value, bool)},
                              "release_sha": data.get("release", {}).get("sha")}
        result["checks"]["platform_pipeline"] = status == 200 and data.get("ok") is True
    except Exception as error:  # noqa: BLE001 — platform failure must not discard native observations
        errors.append("platform:" + type(error).__name__)
        result["checks"]["platform_pipeline"] = False
    result.update({"at": current.isoformat(), "errors": errors})
    result["ok"] = not errors and all(result["checks"].values())
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    args = parser.parse_args()
    root = args.repo.resolve()
    result = capture(root)
    report = root / "var" / "monitor" / "latest.json"
    log_dir = root / "var" / "logs"
    report.parent.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    temporary = report.with_suffix(".tmp")
    temporary.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    temporary.replace(report)
    with (log_dir / ("native-monitor-" + datetime.now(ET).strftime("%Y%m%d") + ".jsonl")).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(result) + "\n")
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
