"""Load 1-minute RTH bars and split them into per-day arrays with the daily context strategies need."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "var" / "data"
MIN_BARS = 300          # Oanda omits minutes with no ticks (2012–2019 medians 320–385); half days and outages fall below 300
FIRST_BAR_MIN = 570     # 09:30 as minute-of-day; the first bar must exist for opening-range rules


@dataclass
class Day:
    date: pd.Timestamp
    mod: np.ndarray      # minute-of-day for each bar (570..959)
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray        # noqa: E741
    c: np.ndarray
    v: np.ndarray
    prev_close: float
    prev_high: float
    prev_low: float
    prev_range: float
    atr14: float         # daily ATR(14) from prior days
    nr7: bool            # prior day's range was the narrowest of the prior 7
    vol_profile: np.ndarray | None  # 20-day mean volume per minute slot (index = mod-570), tick volume here

    def idx_at(self, minute_of_day: int) -> int:
        """First bar index at or after the given minute-of-day (len(mod) if none)."""
        return int(np.searchsorted(self.mod, minute_of_day))

    @property
    def n(self) -> int:
        return len(self.c)


def load_symbol(symbol: str) -> list[Day]:
    """Build the Day list for a symbol from var/data/<symbol>_1m_rth.parquet."""
    df = pd.read_parquet(DATA / f"{symbol}_1m_rth.parquet")
    df["d"] = df.index.normalize()
    df["mod"] = df.index.hour * 60 + df.index.minute
    daily = df.groupby("d").agg(o=("open", "first"), h=("high", "max"), l=("low", "min"), c=("close", "last"), n=("close", "size"))
    tr = np.maximum(daily.h - daily.l, np.maximum((daily.h - daily.c.shift()).abs(), (daily.l - daily.c.shift()).abs()))
    daily["atr14"] = tr.rolling(14).mean().shift()
    daily["rng"] = daily.h - daily.l
    daily["nr7"] = (daily.rng == daily.rng.rolling(7).min()).shift().fillna(False).astype(bool)
    days: list[Day] = []
    groups = dict(tuple(df.groupby("d")))
    dates = list(daily.index)
    hist: list[np.ndarray] = []  # last 20 per-slot volume vectors
    for i, d in enumerate(dates):
        g = groups[d]
        row = daily.loc[d]
        slot = np.full(390, np.nan)
        m = g["mod"].to_numpy()
        ok = (m >= 570) & (m < 960)
        slot[m[ok] - 570] = g["volume"].to_numpy()[ok]
        usable = i > 14 and row.n >= MIN_BARS and m[0] == FIRST_BAR_MIN and not np.isnan(row.atr14)
        if usable:
            prev = daily.iloc[i - 1]
            vp = np.nanmean(np.vstack(hist[-20:]), axis=0) if len(hist) >= 10 else None
            days.append(Day(date=d, mod=m, o=g["open"].to_numpy(float), h=g["high"].to_numpy(float), l=g["low"].to_numpy(float),
                            c=g["close"].to_numpy(float), v=g["volume"].to_numpy(float), prev_close=float(prev.c), prev_high=float(prev.h),
                            prev_low=float(prev.l), prev_range=float(prev.rng), atr14=float(row.atr14), nr7=bool(row.nr7), vol_profile=vp))
        hist.append(slot)
    return days


SYMBOLS = {"SPX500_USD": "SPY proxy (S&P 500 CFD)", "NAS100_USD": "QQQ proxy (Nasdaq 100 CFD)", "US2000_USD": "IWM proxy (Russell 2000 CFD)"}
