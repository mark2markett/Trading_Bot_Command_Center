"""
Signal logic for the SPY Daily Mean Reversion strategy.

Rules (validated 1993-2026 in TradingView, profit factor 2.28, 77% winners):
  ENTER long at the close when  RSI(2) < 10  and  close > SMA(200)
  EXIT  at the close when       close > SMA(5)   or  10 bars held
  CRASH STOP                    exit if price falls 5% below entry (resting stop order)

Pure functions, no I/O, so they can be unit-tested against TradingView values.
"""
from dataclasses import dataclass
from typing import Optional, Sequence


@dataclass(frozen=True)
class Params:
    rsi_len: int = 2
    rsi_entry: float = 10.0
    trend_len: int = 200
    exit_len: int = 5
    max_bars: int = 10
    stop_pct: float = 5.0  # 0 disables


def sma(values: Sequence[float], n: int) -> Optional[float]:
    if len(values) < n:
        return None
    return sum(values[-n:]) / n


def rsi_wilder(closes: Sequence[float], n: int) -> Optional[float]:
    """Wilder RSI, same recursion TradingView's ta.rsi uses (RMA of gains/losses)."""
    if len(closes) < n + 1:
        return None
    gains, losses = [], []
    for a, b in zip(closes[:-1], closes[1:]):
        d = b - a
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    avg_g = sum(gains[:n]) / n
    avg_l = sum(losses[:n]) / n
    for g, l in zip(gains[n:], losses[n:]):
        avg_g = (avg_g * (n - 1) + g) / n
        avg_l = (avg_l * (n - 1) + l) / n
    if avg_l == 0:
        return 100.0
    rs = avg_g / avg_l
    return 100.0 - 100.0 / (1.0 + rs)


@dataclass(frozen=True)
class Snapshot:
    close: float
    rsi: Optional[float]
    sma_trend: Optional[float]
    sma_exit: Optional[float]


def snapshot(closes: Sequence[float], p: Params = Params()) -> Snapshot:
    return Snapshot(
        close=closes[-1],
        rsi=rsi_wilder(closes, p.rsi_len),
        sma_trend=sma(closes, p.trend_len),
        sma_exit=sma(closes, p.exit_len),
    )


def entry_signal(s: Snapshot, p: Params = Params()) -> bool:
    if s.rsi is None or s.sma_trend is None:
        return False
    return s.rsi < p.rsi_entry and s.close > s.sma_trend


def exit_signal(s: Snapshot, bars_held: int, p: Params = Params()) -> Optional[str]:
    """Return a reason string if we should exit, else None."""
    if bars_held >= p.max_bars:
        return "time_stop"
    if s.sma_exit is not None and s.close > s.sma_exit:
        return "exit_sma"
    return None


def stop_price(entry_price: float, p: Params = Params()) -> Optional[float]:
    if p.stop_pct <= 0:
        return None
    return round(entry_price * (1 - p.stop_pct / 100.0), 2)
