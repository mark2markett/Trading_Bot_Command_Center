"""Command-line scaffold shared by intraday bots: `session` (live Schwab data, paper fills), `replay <date>` (offline
replay of a research parquet day through the real runner, so trades appear in the dashboard), `status`."""
from __future__ import annotations

import json
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from . import Bot, BotManifest
from .intraday import ET, Bar, ReplayFeed, Rules, SessionRunner, minutes_of
from .ledger import set_clock, var_dir


def replay_feed(parquet_symbol: str, as_symbol: str, day: datetime) -> ReplayFeed:
    import pandas as pd  # replay only

    df = pd.read_parquet(var_dir() / "data" / f"{parquet_symbol}_1m_rth.parquet")
    df.index = df.index.tz_convert(ET)
    daily = df.groupby(df.index.normalize()).agg(o=("open", "first"), h=("high", "max"), l=("low", "min"), c=("close", "last"), v=("volume", "sum"))
    daily = daily[daily.index < day.replace(hour=0, minute=0, second=0, microsecond=0)]
    dbars = [Bar(t.to_pydatetime(), r.o, r.h, r.l, r.c, r.v) for t, r in daily.tail(40).iterrows()]
    today = df[df.index.normalize() == day.replace(hour=0, minute=0, second=0, microsecond=0)]
    mbars = [Bar(t.to_pydatetime(), r.open, r.high, r.low, r.close, r.volume) for t, r in today.iterrows()]
    if not mbars:
        raise SystemExit(f"no bars for {day.date()} in {parquet_symbol}")
    return ReplayFeed({as_symbol: mbars}, {as_symbol: dbars})


def run_replay(bot: Bot, rules: Rules, symbol: str, parquet_symbol: str, date: str, **kw) -> dict:
    day = datetime.fromisoformat(date).replace(tzinfo=ET)
    feed = replay_feed(parquet_symbol, symbol, day)
    runner = SessionRunner(bot, feed, rules, [symbol], adopt_positions=False, **kw)
    before = bot.L.one("SELECT COALESCE(MAX(id), 0) m FROM trades WHERE bot_id=?", (bot.m.id,))["m"]
    before_dec = bot.L.one("SELECT COALESCE(MAX(id), 0) m FROM decisions WHERE bot_id=?", (bot.m.id,))["m"]
    with bot.run("replay"):
        try:
            set_clock(lambda: feed.clock)   # ledger rows carry the replayed date, so today's risk counters are untouched
            runner.prepare(day)
            for t in minutes_of(day):
                feed.clock = t
                runner.step(t)
        finally:
            set_clock(None)
    trades = [dict(r) for r in bot.L.q(
        "SELECT entry_at, exit_at, qty, entry_px, exit_px, exit_reason, pnl FROM trades WHERE bot_id=? AND id>? ORDER BY id", (bot.m.id, before))]
    bars = feed.minute[symbol]
    why = None
    if not trades:
        first = bars[0].mod if bars else None
        rej = bot.L.one("SELECT reason FROM decisions WHERE bot_id=? AND id>? AND action='NONE' ORDER BY id LIMIT 1", (bot.m.id, before_dec))
        why = (f"signal fired but the risk engine refused it: {rej['reason']} (already replayed this day?)" if rej else
               "no bars for this day" if not bars else
               f"first bar at {first // 60:02d}:{first % 60:02d}, not 09:30 — opening-range rules refuse the day" if first != 570 else
               "rules produced no signal (no gap / no breakout / no setup)")
    return {"date": date, "symbol": symbol, "bars": len(bars), "trades": trades, "realized": round(runner.realized, 2),
            **({"no_trade_reason": why} if why else {})}


def main(manifest: BotManifest, make_rules: Callable[[], Rules], symbols: list[str], bot_dir: Path, replay_map: dict[str, str],
         risk_pct: float = 0.01) -> None:
    bot = Bot(manifest)
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd in ("auth", "check"):
        from .schwab_feed import SchwabFeed

        if cmd == "auth" and "--from-token" in sys.argv:
            # Share a refresh token minted by another system (M2M). Pasted at a hidden prompt; never echoed or logged.
            import getpass

            tok = getpass.getpass("Paste the current Schwab refresh token (input hidden): ")
            issued = None
            if "--issued" in sys.argv:
                issued = datetime.fromisoformat(sys.argv[sys.argv.index("--issued") + 1]).astimezone(ET)
            feed = SchwabFeed.from_refresh_token(bot_dir, tok, issued)
        else:
            feed = SchwabFeed.from_env(bot_dir)   # no token yet -> schwab-py opens the browser login and writes the shared token
        print(json.dumps({"ok": True, **feed.check(symbols[0] if symbols else "SPY")}, indent=2))
    elif cmd == "session":
        from .schwab_feed import SchwabFeed

        feed = SchwabFeed.from_env(bot_dir)
        with bot.run("session"):
            SessionRunner(bot, feed, make_rules(), symbols, risk_pct=risk_pct).loop()
    elif cmd == "replay":
        date = sys.argv[2] if len(sys.argv) > 2 else "2020-03-16"
        sym = sys.argv[3] if len(sys.argv) > 3 else symbols[0]
        print(json.dumps(run_replay(bot, make_rules(), sym, replay_map[sym], date, risk_pct=risk_pct), indent=2, default=str))
    else:
        print(json.dumps({"status": bot.control.status_word(), "positions": bot.positions()}, indent=2, default=str))
