"""Native deployment gate, separate from synthetic closed-loop coverage.

No order/control requests; ledger queried via read-only API. Live probes may refresh
Schwab access tokens and their non-secret issued-time sidecar through the existing SDK.
Exit 0 proves the requested checks only; --configuration-only never certifies live readiness.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cc_sdk"))


def configuration_problems(evidence: dict, values: dict) -> list[str]:
    problems = []
    if not evidence.get("paper_account", {}).get("ready"):
        problems.append("paper_account")
    url = urlsplit(values.get("SCANNER_URL", "").strip())
    if (
        url.scheme != "https"
        or not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
        or len(values.get("SCANNER_SECRET", "")) < 32
    ):
        problems.append("scanner")
    return problems


def values_for(folder: str, previous=None) -> dict:
    values = dict(os.environ if previous is None else previous)
    for path, override in (
        (ROOT / "bots" / folder / ".env", False),
        (ROOT / "bots" / folder / ".env.local", True),
        (ROOT / ".env.local", False),
    ):
        for key, value in dotenv_values(path).items() if path.exists() else []:
            if value is not None and (override or key not in values):
                values[key] = value
    return values


SESSION_TASKS = {
    "CC bot gap_go_bot session",
    "CC bot gap_go_spread_bot session",
    "CC bot nr7_bot session",
    "CC bot sip_orb session",
}


def scheduler_ready(tasks):
    sessions = [t for t in tasks if t.get("TaskName") in SESSION_TASKS]
    return {t["TaskName"] for t in sessions} == SESSION_TASKS and all(
        t.get("Enabled") and t.get("State") == "Running" for t in sessions
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--configuration-only", action="store_true")
    args = parser.parse_args(argv)
    failed = []

    def emit(check, ok, detail):
        print(json.dumps({"check": check, "result": "PASS" if ok else "FAIL", "detail": detail}))
        if not ok:
            failed.append(check)

    try:
        with httpx.Client(timeout=10) as client:
            health = client.get("http://127.0.0.1:8585/api/health")
            health.raise_for_status()
            health = health.json()
            evidence = client.get("http://127.0.0.1:8585/api/readiness")
            evidence.raise_for_status()
            evidence = evidence.json()
        last = datetime.fromisoformat(health["riskd_last"]["at"])
        emit(
            "server/riskd",
            health.get("ok") is True and -30 <= (datetime.now(timezone.utc) - last).total_seconds() <= 90,
            "API and risk monitor freshness",
        )
        emit(
            "fleet", evidence.get("paper_fleet") is True and set(evidence.get("bot_ids", [])) == {"gap_go", "gap_go_spread", "nr7", "sip_orb", "spy_mr"}, "Five registered paper bots required"
        )
        emit("controls", not evidence.get("killed") and not evidence.get("entries_paused"), "Fleet controls must permit entries")
        values = values_for("sip_orb")
        problems = configuration_problems(evidence, values)
        emit("paper_account", "paper_account" not in problems, evidence.get("paper_account", {}).get("reason", "Missing equity"))
        emit(
            "scanner_configuration",
            "scanner" not in problems,
            "HTTPS scanner URL and dedicated secret required; fixed watchlist does not certify scanner readiness",
        )
    except Exception as error:
        emit("native_API", False, type(error).__name__)
        return 1
    from cc_sdk.schwab_feed import SHARED_VARS, SchwabFeed

    for folder in ("gap_go_bot", "gap_go_spread_bot", "nr7_bot", "sip_orb", "spy_mr_bot"):
        env = values_for(folder)
        shared = all(env.get(k, "").strip() for k in SHARED_VARS) and env.get("SUPABASE_URL", "").startswith("https://")
        broker = env.get("CC_TOKEN_BROKER_URL", "").startswith("https://") and len(env.get("CC_TOKEN_BROKER_SECRET", "")) >= 32
        emit(folder + "_feed_config", shared or broker, "Existing shared Schwab or token-broker configuration required")
    if failed:
        return 1
    if args.configuration_only:
        print("CONFIGURATION ONLY: live quote freshness and today's scanner snapshot remain unverified.")
        return 0
    from cc_sdk.intraday import ET

    sys.path.insert(0, str(ROOT / "cc_server"))
    from cc_server import calendar

    current = datetime.now(ET)
    closing = 780 if calendar.is_early_close(current.date()) else 960
    if not (
        2025 <= current.year <= 2027
        and calendar.is_trading_day(current.date())
        and 570 <= current.hour * 60 + current.minute < closing
    ):
        emit(
            "live_window",
            False,
            "Run live readiness during the trading session; configuration-only check is available outside it",
        )
        return 1
    if os.name != "nt":
        emit("Windows_scheduler", False, "Native Windows scheduler evidence is required")
        return 1
    try:
        command = "Get-ScheduledTask -TaskName 'CC bot *','CC server' | Select-Object TaskName,@{Name='State';Expression={$_.State.ToString()}},@{Name='Enabled';Expression={$_.Settings.Enabled}},@{Name='LogonType';Expression={$_.Principal.LogonType.ToString()}} | ConvertTo-Json -Compress"
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", command], capture_output=True, text=True, timeout=15, check=True
        )
        tasks = json.loads(result.stdout)
        emit("Windows_sessions", scheduler_ready(tasks), "All four native session tasks must be enabled and running")
        if any(t.get("LogonType") == "Interactive" for t in tasks):
            print(
                "SCHEDULER LIMITATION: interactive tasks require the Windows user to remain signed in; sign-out survival is unverified."
            )
    except Exception as error:
        emit("Windows_scheduler", False, type(error).__name__)
    previous = dict(os.environ)
    try:
        # Isolate each bot's configuration, including broker-only installations.
        for folder in ("gap_go_bot", "gap_go_spread_bot", "nr7_bot", "sip_orb", "spy_mr_bot"):
            env = values_for(folder, previous)
            os.environ.clear()
            os.environ.update(env)
            try:
                feed = SchwabFeed.connect(ROOT / "bots" / folder)
                price, age = feed.quote("SPY")
                emit(folder + "_live_quote", price > 0 and 0 <= age <= 90, "Positive SPY quote no older than 90 seconds")
                bars = [b for b in feed.minute_bars("SPY", current) if b.t < current.replace(second=0, microsecond=0)]
                emit(
                    folder + "_minute_history",
                    bool(bars) and 0 <= (datetime.now(ET) - bars[-1].t).total_seconds() <= 180,
                    "Completed SPY minute history no older than 180 seconds",
                )
            except Exception as error:
                emit(folder + "_live_quote", False, type(error).__name__)
        os.environ.clear()
        os.environ.update(values)
        try:
            spec = importlib.util.spec_from_file_location("native_sip_scanner", ROOT / "bots/sip_orb/sip_scanner.py")
            scanner = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(scanner)
            data = scanner.fetch(values["SCANNER_URL"])
            symbols = scanner.parse_snapshot(data, datetime.now(ET))
            emit("today_scanner", True, f"Validated authenticated completed opening window; selected={len(symbols)}")
        except Exception as error:
            emit("today_scanner", False, type(error).__name__ + "; require a fresh published snapshot at 09:35–09:39 ET")
    finally:
        os.environ.clear()
        os.environ.update(previous)
    print("LIVE READINESS PASS" if not failed else "NOT READY: resolve every failed prerequisite.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
