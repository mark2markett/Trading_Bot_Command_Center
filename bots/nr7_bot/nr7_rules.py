"""NR7 breakout rules (incremental form of research/strategies.py::nr7_breakout, best cell: stop 0.25 ATR, target 2R)."""
from __future__ import annotations

from cc_sdk.intraday import Bar, DayContext, Signal


class NR7Rules:
    name = "nr7_breakout"

    def __init__(self, stop_atr: float = 0.25, target_r: float | None = 2.0):
        self.stop_atr, self.target_r = stop_atr, target_r

    def decide(self, bars: list[Bar], ctx: DayContext) -> Signal | None:
        if not ctx.nr7 or not bars:
            return None
        last = bars[-1]
        off = self.stop_atr * ctx.atr14
        if last.c > ctx.prev_high:
            return Signal(1, "NR7 day · prior high broken", stop_offset=off, target_r=self.target_r)
        if last.c < ctx.prev_low:
            return Signal(-1, "NR7 day · prior low broken", stop_offset=off, target_r=self.target_r)
        return None
