"""Gap-and-go rules (incremental form of research/strategies.py::gap_go). Pure: bars + prior-day context -> Signal."""
from __future__ import annotations

from cc_sdk.intraday import Bar, DayContext, Signal

OPEN_MIN = 570


class GapGoRules:
    name = "gap_go"

    def __init__(self, gap_bps: float = 70.0, wait_min: int = 30):
        self.gap_bps, self.wait_min = gap_bps, wait_min

    def decide(self, bars: list[Bar], ctx: DayContext) -> Signal | None:
        if not bars or bars[0].mod != OPEN_MIN:
            return None
        gap = (bars[0].o / ctx.prev_close - 1) * 1e4
        if abs(gap) < self.gap_bps:
            return None
        side = 1 if gap > 0 else -1
        rng = [b for b in bars if b.mod < OPEN_MIN + self.wait_min]
        last = bars[-1]
        if not rng or last.mod < OPEN_MIN + self.wait_min:
            return None
        hi, lo = max(b.h for b in rng), min(b.l for b in rng)
        if side > 0 and last.c > hi:
            return Signal(1, f"gap +{gap:.0f}bp, {self.wait_min}m range broken up", stop=lo)
        if side < 0 and last.c < lo:
            return Signal(-1, f"gap {gap:.0f}bp, {self.wait_min}m range broken down", stop=hi)
        return None
