"""Load actual bot code from an isolated source copy; never copy runtime/credentials."""
from __future__ import annotations

import importlib.util
import logging
import os
import shutil
import sys
from pathlib import Path
from uuid import uuid4

from scripts.closed_loop_guard import SandboxError, validate_sandbox
from scripts.closed_loop_report import NotCovered, Report

FOLDERS = {"gap_go": "gap_go_bot", "nr7": "nr7_bot", "sip_orb": "sip_orb",
           "spy_mr": "spy_mr_bot", "gap_go_spread": "gap_go_spread_bot"}


def load_sources(repo: Path, runtime: Path) -> dict:
    expected = runtime.resolve()
    runtime = validate_sandbox(repo, os.getenv("CC_VAR"))
    if runtime != expected or os.getenv("MODE", "paper") != "paper":
        raise SandboxError("Source loading requires the validated paper worker environment")
    mirror = runtime.parent / "imports" / "bots"
    (runtime / "control").mkdir(parents=True, exist_ok=True)
    for folder in FOLDERS.values():
        target = mirror / folder
        target.mkdir(parents=True, exist_ok=True)
        for source in (repo / "bots" / folder).glob("*.py"):
            shutil.copyfile(source, target / source.name)
    names = ("cc", "broker", "strategy", "gap_go_rules", "nr7_rules", "sip_orb_rules", "sip_scanner")
    previous = {name: sys.modules.pop(name, None) for name in names}
    paths = sys.path[:]
    modules = {}
    try:
        sys.path[:0] = [str(mirror / folder) for folder in FOLDERS.values()]
        for bot_id, folder in FOLDERS.items():
            name = f"_closed_loop_{bot_id}_{uuid4().hex}"
            spec = importlib.util.spec_from_file_location(name, mirror / folder / "bot.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            manifest = module.cc.MANIFEST if bot_id == "spy_mr" else module.MANIFEST
            if manifest.mode != "paper":
                raise SandboxError("An imported manifest is not paper-only")
            modules[bot_id] = module
    finally:
        sys.path[:] = paths
        for name in names:
            sys.modules.pop(name, None)
            if previous[name] is not None:
                sys.modules[name] = previous[name]
    logging.getLogger("bot").setLevel(logging.ERROR)
    return modules


def load_fleet(repo: Path, runtime: Path) -> tuple[dict, dict]:
    from cc_sdk import Bot

    modules = load_sources(repo, runtime)
    bots = {}
    for bot_id, module in modules.items():
        bots[bot_id] = (module.cc.bot if bot_id == "spy_mr" else
                        Bot(module.MANIFEST, db_path=runtime / "cc.db", control_dir=runtime / "control"))
        if bots[bot_id] is None:
            raise RuntimeError("Daily bot SDK initialization failed")
        bots[bot_id].L.heartbeat(bot_id, "session" if bot_id != "spy_mr" else "decide", True, "SYNTHETIC harness")
    return bots, modules


def replay_one(context, bot_id: str, symbol: str, parquet_symbol: str, max_days: int = 250) -> str:
    """Bounded search using real rules, then actual run_replay; source parquet remains read-only."""
    if not 1 <= max_days <= 250:
        raise ValueError("History search must be between 1 and 250 trading days")
    source = context.repo / "var" / "data" / f"{parquet_symbol}_1m_rth.parquet"
    if not source.is_file():
        raise NotCovered(f"{parquet_symbol} parquet absent; bundle does not include local var/data")
    import pandas as pd
    from cc_sdk.intraday import ET, Bar, day_context
    from cc_sdk.intraday_cli import run_replay

    df = pd.read_parquet(source)
    if not isinstance(df.index, pd.DatetimeIndex) or df.index.tz is None:
        raise ValueError("History needs a timezone-aware DatetimeIndex")
    if not {"open", "high", "low", "close", "volume"}.issubset(df.columns):
        raise ValueError("History is missing required OHLCV columns")
    if df.empty:
        raise NotCovered("Historical parquet has no bars")
    df = df.sort_index()
    df.index = df.index.tz_convert(ET)
    days = df.index.normalize().unique().sort_values()
    candidates = days[-max_days:]
    trimmed = df[df.index.normalize() >= days[-min(len(days), max_days + 40)]]
    target = context.runtime / "data" / source.name
    target.parent.mkdir(parents=True, exist_ok=True)
    trimmed.to_parquet(target)
    daily = trimmed.groupby(trimmed.index.normalize()).agg(
        o=("open", "first"), h=("high", "max"), l=("low", "min"), c=("close", "last"), v=("volume", "sum"))
    rules_name = "GapGoRules" if bot_id == "gap_go" else "NR7Rules"
    rules = getattr(context.modules[bot_id], rules_name)()
    bot = context.bots[bot_id]
    for day in reversed(candidates):
        prior = daily[daily.index < day].tail(40)
        if len(prior) < 16:
            continue
        ctx = day_context([Bar(t.to_pydatetime(), r.o, r.h, r.l, r.c, r.v) for t, r in prior.iterrows()])
        bars = [Bar(t.to_pydatetime(), r.open, r.high, r.low, r.close, r.volume)
                for t, r in trimmed[trimmed.index.normalize() == day].iterrows()]
        # Entry candidates are completed bars before the runner's 15:58 flatten cutoff.
        signal = any(rules.decide(bars[:i + 1], ctx) for i, bar in enumerate(bars) if bar.mod < 957)
        if not signal:
            continue
        before = {table: bot.L.one(f"SELECT COUNT(*) n FROM {table} WHERE bot_id=?", (bot_id,))["n"]
                  for table in ("orders", "fills", "trades")}
        result = run_replay(bot, rules, symbol, parquet_symbol, day.date().isoformat(),
                            risk_pct=0.005 if bot_id == "nr7" else 0.01)
        counts = {table: bot.L.one(f"SELECT COUNT(*) n FROM {table} WHERE bot_id=?", (bot_id,))["n"] - before[table]
                  for table in before}
        assert result["trades"] and all(counts.values()), "Historical signal fired but orders/fills/closed trade did not complete"
        return f"{day.date()} {parquet_symbol} -> {symbol}: {counts['orders']} orders, {counts['fills']} fills, {counts['trades']} closed trades"
    raise NotCovered(f"No qualifying {rules_name} signal in {len(candidates)} trading days ({candidates[0].date()}–{candidates[-1].date()})")


def replay_history(context, report: Report, max_days: int = 250) -> None:
    maps = {"gap_go": [("SPY", "SPX500_USD"), ("QQQ", "NAS100_USD")],
            "nr7": [("SPY", "SPX500_USD"), ("IWM", "US2000_USD")]}
    for bot_id, pairs in maps.items():
        def run(bot_id=bot_id, pairs=pairs):
            missing = []
            for symbol, parquet in pairs:
                try:
                    return replay_one(context, bot_id, symbol, parquet, max_days)
                except NotCovered as exc:
                    missing.append(str(exc))
            raise NotCovered("; ".join(missing))
        report.check(f"Historical replay {bot_id}", run)


def check_data(context, report: Report) -> None:
    """Never load credential files or rotate shared Supabase auth as part of a test."""
    def schwab():
        shared = ("SCHWAB_CLIENT_ID", "SCHWAB_CLIENT_SECRET", "SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY")
        if all(os.getenv(key) for key in shared):
            raise NotCovered("Shared-state Schwab authentication can rotate/write Supabase; excluded from isolated test")
        if not all(os.getenv(key) for key in ("CC_TOKEN_BROKER_URL", "CC_TOKEN_BROKER_SECRET")):
            raise NotCovered("Injected CC_TOKEN_BROKER_URL/CC_TOKEN_BROKER_SECRET absent; no credential files read")
        from cc_sdk.schwab_feed import SchwabFeed
        feed = SchwabFeed.from_broker(context.runtime)
        try:
            result = feed.check("SPY")
            assert result["last"] > 0 and result["minute_bars_today"] >= 0, "Schwab data response invalid"
            return f"Quote received; age={result['quote_age_s']}s; minute bars today={result['minute_bars_today']} (market-closed staleness allowed)"
        finally:
            feed.c._http.close()

    def polygon():
        if not os.getenv("POLYGON_API_KEY"):
            raise NotCovered("Injected POLYGON_API_KEY absent; no credential files read")
        from datetime import datetime, timedelta

        from cc_sdk.intraday import ET
        from cc_sdk.polygon_options import polygon_from_env
        today = datetime.now(ET).date()
        feed = polygon_from_env()
        try:
            quotes = feed.snapshot("SPY", today, today + timedelta(days=7))
            assert quotes, "Polygon returned no option contracts"
            return f"{len(quotes)} option contracts received (freshness not asserted while market closed)"
        finally:
            feed._http.close()
    report.check("Real Schwab data", schwab)
    report.check("Real Polygon options", polygon)
