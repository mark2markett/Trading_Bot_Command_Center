"""NYSE holidays and early closes, 2025–2027. Hand-maintained; extend each December."""
from __future__ import annotations

from datetime import date, timedelta

HOLIDAYS: set[date] = {
    # 2025
    date(2025, 1, 1), date(2025, 1, 9), date(2025, 1, 20), date(2025, 2, 17), date(2025, 4, 18), date(2025, 5, 26),
    date(2025, 6, 19), date(2025, 7, 4), date(2025, 9, 1), date(2025, 11, 27), date(2025, 12, 25),
    # 2026
    date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16), date(2026, 4, 3), date(2026, 5, 25), date(2026, 6, 19),
    date(2026, 7, 3), date(2026, 9, 7), date(2026, 11, 26), date(2026, 12, 25),
    # 2027
    date(2027, 1, 1), date(2027, 1, 18), date(2027, 2, 15), date(2027, 3, 26), date(2027, 5, 31), date(2027, 6, 18),
    date(2027, 7, 5), date(2027, 9, 6), date(2027, 11, 25), date(2027, 12, 24),
}

EARLY_CLOSES: set[date] = {  # 1:00 pm ET
    date(2025, 7, 3), date(2025, 11, 28), date(2025, 12, 24),
    date(2026, 11, 27), date(2026, 12, 24),
    date(2027, 11, 26),
}


def is_trading_day(d: date) -> bool:
    return d.weekday() < 5 and d not in HOLIDAYS


def is_early_close(d: date) -> bool:
    return d in EARLY_CLOSES


def next_trading_day(d: date) -> date:
    d = d + timedelta(days=1)
    while not is_trading_day(d):
        d += timedelta(days=1)
    return d


def next_early_close(d: date) -> date | None:
    cands = sorted(x for x in EARLY_CLOSES if x >= d)
    return cands[0] if cands else None


def close_time_str(d: date) -> str:
    return "13:00" if is_early_close(d) else "16:00"


def decide_time_str(d: date) -> str:
    """Daily bots decide 10 minutes before the close."""
    return "12:50" if is_early_close(d) else "15:50"
