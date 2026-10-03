"""Pull 1-minute regular-hours bars from Schwab into var/data/<SYMBOL>_1m_rth.parquet, in the harness's format.
Appends to and de-duplicates against an existing file, so running it weekly accumulates history past Schwab's lookback.

Usage (from a bot folder that has Schwab credentials in .env, e.g. bots/gap_go_bot):
    python ..\\..\\research\\schwab_dump.py SPY QQQ IWM [--days 180]
Then:  python -m research.run_all --symbols SPY,QQQ,IWM
Schwab's minute history reaches back a limited number of months; the script walks backwards in 7-day windows and stops
after three consecutive empty windows. Rate limit: ~120 requests/min; this script sleeps 0.6 s between calls.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cc_sdk"))
from cc_sdk.ledger import token_path  # noqa: E402

ET = ZoneInfo("America/New_York")
OUT = ROOT / "var" / "data"


def client():
    try:
        from dotenv import load_dotenv

        load_dotenv(Path.cwd() / ".env")
    except ImportError:
        pass
    from schwab.auth import easy_client

    missing = [k for k in ("SCHWAB_API_KEY", "SCHWAB_APP_SECRET", "SCHWAB_CALLBACK_URL") if not os.getenv(k)]
    if missing:
        raise SystemExit(f"run from a bot folder whose .env has Schwab credentials; missing {', '.join(missing)}")
    return easy_client(api_key=os.environ["SCHWAB_API_KEY"], app_secret=os.environ["SCHWAB_APP_SECRET"],
                       callback_url=os.environ["SCHWAB_CALLBACK_URL"], token_path=str(token_path(Path.cwd())))


def fetch(c, symbol: str, days: int) -> pd.DataFrame:
    end = datetime.now(ET)
    frames, empty = [], 0
    while (datetime.now(ET) - end).days < days and empty < 3:
        start = end - timedelta(days=7)
        r = c.get_price_history_every_minute(symbol, start_datetime=start, end_datetime=end, need_extended_hours_data=False)
        if r.status_code != 200:
            print(f"{symbol}: HTTP {r.status_code} {r.text[:120]}", file=sys.stderr)
            break
        candles = r.json().get("candles", [])
        if candles:
            df = pd.DataFrame(candles)
            df["time"] = pd.to_datetime(df["datetime"], unit="ms", utc=True).dt.tz_convert(ET)
            frames.append(df[["time", "close", "high", "low", "open", "volume"]])
            empty = 0
        else:
            empty += 1
        print(f"{symbol}: {start:%Y-%m-%d} → {end:%Y-%m-%d}: {len(candles)} bars")
        end = start
        time.sleep(0.6)
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames).set_index("time").sort_index()
    return df[~df.index.duplicated()].between_time("09:30", "15:59")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("symbols", nargs="+")
    ap.add_argument("--days", type=int, default=180)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    c = client()
    for sym in a.symbols:
        new = fetch(c, sym, a.days)
        path = OUT / f"{sym}_1m_rth.parquet"
        if path.exists() and not new.empty:
            old = pd.read_parquet(path)
            new = pd.concat([old, new]).sort_index()
            new = new[~new.index.duplicated(keep="last")]
        if new.empty:
            print(f"{sym}: nothing fetched")
            continue
        new.to_parquet(path)
        days_n = new.index.normalize().nunique()
        print(f"{sym}: {len(new)} bars, {days_n} days, {new.index.min().date()} → {new.index.max().date()} -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
