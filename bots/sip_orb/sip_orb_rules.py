"""Stocks-in-Play opening-range breakout (Zarattini, Barbon, Aziz 2024). Pure rules.
Direction = first 5-minute candle; entry when a later bar closes beyond the opening range in that direction;
stop = 10% of the 14-day ATR from the fill; no target; flat at the close."""
from __future__ import annotations

from cc_sdk.intraday import Bar, DayContext, Signal

OPEN_MIN = 570


class SipOrbRules:
    name = "sip_orb"

    def __init__(self, range_min: int = 5, stop_atr: float = 0.10):
        self.range_min, self.stop_atr = range_min, stop_atr

    def decide(self, bars: list[Bar], ctx: DayContext) -> Signal | None:
        if not bars or bars[0].mod != OPEN_MIN:
            return None
        rng = [b for b in bars if b.mod < OPEN_MIN + self.range_min]
        last = bars[-1]
        if not rng or last.mod < OPEN_MIN + self.range_min:
            return None
        move = rng[-1].c - rng[0].o
        if move == 0:
            return None
        side = 1 if move > 0 else -1
        hi, lo = max(b.h for b in rng), min(b.l for b in rng)
        off = self.stop_atr * ctx.atr14
        if side > 0 and last.c > hi:
            return Signal(1, f"first {self.range_min}m up · OR high broken", stop_offset=off)
        if side < 0 and last.c < lo:
            return Signal(-1, f"first {self.range_min}m down · OR low broken", stop_offset=off)
        return None
