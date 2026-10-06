"""Intraday session framework shared by every intraday bot.

A bot supplies a `Rules` object (pure: bars in, Signal out) and a `Feed` (minute bars + quotes). The runner owns the
session loop, risk checks, paper fills, stops, end-of-day flatten, control flags and heartbeats. One trade per symbol per
day — the same convention the research harness used, so replay parity is testable.

Nothing here touches Schwab directly; `schwab_feed.SchwabFeed` is the only Schwab-aware class and lives in its own module.
"""
from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any, Protocol
from zoneinfo import ZoneInfo

import httpx

from . import Bot, Order
from .ledger import now_iso

ET = ZoneInfo("America/New_York")
OPEN_MIN, CLOSE_MIN = 570, 960           # 09:30, 16:00 as minutes of day
FLATTEN_MIN = 958                        # 15:58: send market exits before the bell
SLIPPAGE_BPS = 1.0                       # paper fills: quote ± 1 bp (matches the backtest cost model)


class UniversePending(Exception):
    """Retryable delayed universe; the runner must continue managing open positions."""


@dataclass
class Bar:
    t: datetime        # bar start, ET
    o: float
    h: float
    l: float           # noqa: E741
    c: float
    v: float

    @property
    def mod(self) -> int:
        return self.t.hour * 60 + self.t.minute


@dataclass
class DayContext:
    """Prior-day facts a rule set may need. Filled by the runner once per symbol per session from daily bars."""
    prev_close: float
    prev_high: float
    prev_low: float
    atr14: float
    nr7: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class Signal:
    side: int                        # +1 long, -1 short
    reason: str
    stop: float | None = None        # absolute stop price (range-based rules)
    stop_offset: float | None = None  # or: stop = fill - side * stop_offset (ATR-fraction rules)
    target_r: float | None = None    # optional target in multiples of the stop distance

    def resolve(self, fill: float) -> tuple[float, float | None]:
        stop = self.stop if self.stop is not None else fill - self.side * float(self.stop_offset or 0)
        if stop == fill:
            raise ValueError("signal has no stop")
        target = fill + self.side * self.target_r * abs(fill - stop) if self.target_r else None
        return stop, target


class Rules(Protocol):
    name: str

    def decide(self, bars: list[Bar], ctx: DayContext) -> Signal | None:
        """Called on every poll while the symbol is flat and untraded today. bars = today's completed minute bars."""


class Feed(Protocol):
    def minute_bars(self, symbol: str, day: datetime) -> list[Bar]: ...
    def quote(self, symbol: str) -> tuple[float, float]:
        """(last price, quote age in seconds)."""
    def daily_bars(self, symbol: str, n: int) -> list[Bar]: ...


def day_context(daily: list[Bar]) -> DayContext:
    """Compute prior-day facts from daily bars that END with the prior session (today's bar excluded)."""
    if len(daily) < 16:
        raise ValueError("need ≥16 daily bars for ATR(14) and NR7")
    prev = daily[-1]
    trs = [max(b.h - b.l, abs(b.h - p.c), abs(b.l - p.c)) for p, b in zip(daily[-15:-1], daily[-14:], strict=True)]
    rng = [b.h - b.l for b in daily[-7:]]
    return DayContext(prev_close=prev.c, prev_high=prev.h, prev_low=prev.l, atr14=sum(trs) / 14, nr7=(prev.h - prev.l) <= min(rng))


def size_by_risk(entry: float, stop: float, risk_usd: float, max_position_usd: float, max_qty: int) -> int:
    per_share = abs(entry - stop)
    if per_share <= 0:
        return 0
    qty = int(risk_usd // per_share)
    qty = min(qty, int(max_position_usd // entry), max_qty)
    return max(qty, 0)


@dataclass
class OpenPos:
    symbol: str
    side: int
    qty: int
    entry_px: float
    stop: float
    target: float | None
    entry_at: str
    order_id: int | None


class SessionRunner:
    """Drives one trading session for a bot across its symbols. `step(now)` is pure enough to unit-test; `loop()` wraps it."""

    def __init__(self, bot: Bot, feed: Feed, rules: Rules, symbols: list[str], *, risk_pct: float = 0.01,
                 paper_equity: float = 100_000.0, poll_s: int = 15,
                 universe_fn: Callable[[datetime], list[str]] | None = None, universe_at_mod: int = OPEN_MIN + 5,
                 adopt_positions: bool = True, universe_deadline_mod: int = OPEN_MIN + 10):
        """universe_fn: optional late-binding symbol list (e.g. a 09:35 stocks-in-play scan). Until it runs, no entries.
        adopt_positions: pick up positions left in the ledger by a crashed session (off for offline replays)."""
        self.adopt_positions = adopt_positions
        self.bot, self.feed, self.rules, self.symbols = bot, feed, rules, list(symbols)
        self.risk_pct, self.equity, self.poll_s = risk_pct, paper_equity, poll_s
        self.universe_fn, self.universe_at_mod, self.universe_done = universe_fn, universe_at_mod, universe_fn is None
        self.universe_deadline_mod = universe_deadline_mod
        self._universe_failure = False
        self.ctx: dict[str, DayContext] = {}
        self.open: dict[str, OpenPos] = {}
        self.traded_today: set[str] = set()
        self.realized: float = 0.0
        self.log: list[str] = []
        self._diagnostic_at: dict[str, float] = {}
        self._poll_errors: dict[str, str] = {}

    @staticmethod
    def _error_summary(error: Exception) -> str:
        # URLs, response bodies and exception messages can contain credentials.
        if isinstance(error, httpx.HTTPStatusError):
            return f"HTTP {error.response.status_code}"
        return type(error).__name__

    def _data_error(self, symbol: str, operation: str, error: Exception) -> None:
        reason = f"{operation}: {self._error_summary(error)}; retry next poll"
        self._poll_errors[symbol] = reason
        self.bot.L.decision(self.bot.m.id, "session", {"symbol": symbol, "operation": operation}, "NO_DATA", reason)
        self.bot.event("data_error", symbol=symbol, operation=operation, error=self._error_summary(error))

    def _record_no_signal(self, symbol: str, bars: list[Bar], now: datetime) -> None:
        if now.timestamp() - self._diagnostic_at.get(symbol, 0.0) < 300:
            return
        self._diagnostic_at[symbol] = now.timestamp()
        signal = {"symbol": symbol, "bars": len(bars), "context": asdict(self.ctx[symbol]),
                  "first_open": bars[0].o if bars else None,
                  "last_bar": bars[-1].t.isoformat() if bars else None,
                  "last_close": bars[-1].c if bars else None}
        action = "NO_SIGNAL" if bars else "NO_BARS"
        self.bot.L.decision(self.bot.m.id, "session", signal, action,
                            "rules produced no signal" if bars else "no completed minute bars")

    # ---- session lifecycle ----
    def prepare(self, day: datetime) -> None:
        for s in self.symbols:
            if s in self.ctx:
                continue
            try:
                daily = [b for b in self.feed.daily_bars(s, 40) if b.t.date() < day.date()]
                self.ctx[s] = day_context(daily)
            except Exception as e:  # noqa: BLE001 — one bad symbol must not stop the session
                self.bot.L.decision(self.bot.m.id, "session", {"symbol": s}, "SKIP", f"no daily context: {e}")
        self.symbols = [s for s in self.symbols if s in self.ctx]
        for p in (self.bot.positions() if self.adopt_positions else []):   # left by a crashed session: adopt so EOD flatten happens
            if p["qty"]:
                self.open[p["symbol"]] = OpenPos(p["symbol"], 1 if p["side"] != "SHORT" else -1, abs(int(p["qty"])), float(p["avg_price"]),
                                                 float(p["stop_price"] or 0), None, p["entry_at"], None)
                self.traded_today.add(p["symbol"])

    def step(self, now: datetime) -> None:
        """One poll. Order of operations: controls → exits (stops, flatten, EOD) → entries."""
        mod = now.hour * 60 + now.minute
        self._poll_errors = {"scanner": "scanner unavailable at deadline"} if self._universe_failure else {}
        killed = self.bot.control.killed()
        flatten = killed or self.bot.control.flatten_requested() or mod >= FLATTEN_MIN
        for s in list(self.open):
            try:
                px, age = self.feed.quote(s)
            except Exception as e:  # noqa: BLE001 — no quote: keep the position, try again next poll, leave a trace
                self._data_error(s, "quote", e)
                continue
            pos = self.open[s]
            if flatten:
                self._exit(pos, px, age, "kill" if killed else ("flatten" if mod < FLATTEN_MIN else "eod"))
            elif (pos.side > 0 and px <= pos.stop) or (pos.side < 0 and px >= pos.stop):
                self._exit(pos, px, age, "stop")
            elif pos.target and ((pos.side > 0 and px >= pos.target) or (pos.side < 0 and px <= pos.target)):
                self._exit(pos, px, age, "target")
        if flatten and not self.open and self.bot.control.flatten_requested():
            self.bot.control.clear_flatten()
        if not self.universe_done and self.universe_fn is not None and mod >= self.universe_deadline_mod:
            self.symbols = []
            self.universe_done = True
            self._universe_failure = True
            self._poll_errors["scanner"] = "scanner unavailable at deadline"
            self.bot.L.decision(self.bot.m.id, "session", {}, "SCANNER_UNAVAILABLE", "no valid universe by 09:40 ET; entries disabled, exits continue")
            self.bot.event("scanner_unavailable", deadline_mod=self.universe_deadline_mod)
            return
        if killed or flatten or self.bot.control.entries_paused() or mod < OPEN_MIN + 1:
            return
        if not self.universe_done and mod >= self.universe_at_mod and self.universe_fn is not None:
            try:
                self.symbols = self.universe_fn(now)
            except UniversePending:
                self._poll_errors["scanner"] = "snapshot pending; retry next poll"
                return
            self.prepare(now)
            self.universe_done = True
            self.bot.L.decision(self.bot.m.id, "session", {"universe": self.symbols}, "UNIVERSE", f"{len(self.symbols)} symbols selected")
        if not self.universe_done:
            return
        for s in self.symbols:
            if s in self.open or s in self.traded_today:
                continue
            try:
                bars = [b for b in self.feed.minute_bars(s, now) if b.mod < mod]   # completed bars only
            except httpx.HTTPError as e:
                if not isinstance(e, httpx.RequestError) and not (
                    isinstance(e, httpx.HTTPStatusError) and (e.response.status_code == 429 or e.response.status_code >= 500)
                ):
                    raise
                self._data_error(s, "minute_bars", e)
                continue
            if not bars:
                self._record_no_signal(s, bars, now)
                continue
            sig = self.rules.decide(bars, self.ctx[s])
            if sig:
                try:
                    self._enter(s, sig, now)
                except Exception as e:  # noqa: BLE001 — a failed entry must not kill the session for the other symbols
                    self.bot.L.decision(self.bot.m.id, "session", {"symbol": s, "signal": sig.reason}, "NONE", f"entry failed: {e}"[:200])
                    self.traded_today.add(s)
            else:
                self._record_no_signal(s, bars, now)

    def loop(self, day: datetime | None = None) -> None:
        day = day or datetime.now(ET)
        self.prepare(day)
        last_hb = 0.0
        while True:
            now = datetime.now(ET)
            if now.hour * 60 + now.minute >= CLOSE_MIN and not self.open:
                break
            self.step(now)
            if time.time() - last_hb > 300:
                detail = {"open": list(self.open), "realized": round(self.realized, 2), "symbols": self.symbols,
                          "universe_ready": self.universe_done, "data_errors": self._poll_errors}
                ok = not self._poll_errors
                self.bot.L.heartbeat(self.bot.m.id, "session", ok=ok, detail=json.dumps(detail))
                self.bot.event("heartbeat", ok=ok, **detail)
                last_hb = time.time()
            time.sleep(self.poll_s)
        self.bot.record_equity(self.equity + self.realized, source="bot")

    # ---- orders (paper) ----
    def _enter(self, s: str, sig: Signal, now: datetime) -> None:
        px, age = self.feed.quote(s)
        lim = self.bot.m.limits
        stop, target = sig.resolve(px)
        qty = size_by_risk(px, stop, self.risk_pct * self.equity, lim["max_position_usd"], lim["max_order_qty"])
        if qty <= 0:
            self.bot.L.decision(self.bot.m.id, "session", {"symbol": s, "signal": sig.reason}, "NONE", "size 0 (stop too wide)")
            self.traded_today.add(s)
            return
        o = Order(side="BUY" if sig.side > 0 else "SELL_SHORT", qty=qty, type="MKT", symbol=s, ref_price=px, quote_age_s=age, stop_price=stop)
        r = self.bot.risk.pre_trade(o)
        if not r.ok:
            self.bot.L.decision(self.bot.m.id, "session", {"symbol": s, "signal": sig.reason}, "NONE", f"rejected: {r.reason}")
            self.traded_today.add(s)
            return
        oid = self.bot.L.order(self.bot.m.id, side=o.side, qty=qty, type_="MKT", symbol=s, status="sent", reason=sig.reason,
                               risk_result=r.to_dict(), broker_order_id=f"paper-{now_iso()}", stop_price=stop, ref_price=px)
        fill = px * (1 + sig.side * SLIPPAGE_BPS / 1e4)
        self.bot.record_fill(oid, qty, fill, px)
        self.bot.set_position(s, qty * sig.side, fill, now_iso(), 0, stop, "LONG" if sig.side > 0 else "SHORT")
        self.bot.L.decision(self.bot.m.id, "session", {"symbol": s, "px": px, "stop": stop, "target": target, "qty": qty}, "ENTER", sig.reason)
        self.open[s] = OpenPos(s, sig.side, qty, fill, stop, target, now_iso(), oid)
        self.traded_today.add(s)

    def _exit(self, pos: OpenPos, px: float, age: float, reason: str) -> None:
        side = "SELL" if pos.side > 0 else "BUY_TO_COVER"
        o = Order(side=side, qty=pos.qty, type="MKT", symbol=pos.symbol, ref_price=px, quote_age_s=age, reduces_risk=True)
        r = self.bot.risk.pre_trade(o)          # risk-reducing: never blocked by pause/kill, still audited
        oid = self.bot.L.order(self.bot.m.id, side=side, qty=pos.qty, type_="MKT", symbol=pos.symbol, status="sent", reason=reason,
                               risk_result=r.to_dict(), broker_order_id=f"paper-{now_iso()}", ref_price=px)
        fill = px * (1 - pos.side * SLIPPAGE_BPS / 1e4)
        self.bot.record_fill(oid, pos.qty, fill, px)
        pnl = pos.side * (fill - pos.entry_px) * pos.qty
        self.realized += pnl
        self.bot.record_trade(entry_at=pos.entry_at, exit_at=now_iso(), qty=pos.qty * pos.side, entry_px=pos.entry_px, exit_px=fill, bars=0,
                              exit_reason=reason, pnl=round(pnl, 2), slippage=abs(fill - px))
        self.bot.set_position(pos.symbol, 0)
        self.bot.L.decision(self.bot.m.id, "session", {"symbol": pos.symbol, "px": px, "pnl": round(pnl, 2)}, "EXIT", reason)
        del self.open[pos.symbol]


class ReplayFeed:
    """Feed over in-memory bars for tests and offline replays. `clock` is the current time the runner is pretending it is."""

    def __init__(self, minute: dict[str, list[Bar]], daily: dict[str, list[Bar]]):
        self.minute, self.daily = minute, daily
        self.clock: datetime | None = None

    def minute_bars(self, symbol: str, day: datetime) -> list[Bar]:
        cut = self.clock or day
        return [b for b in self.minute[symbol] if b.t.date() == day.date() and b.t < cut]

    def quote(self, symbol: str) -> tuple[float, float]:
        assert self.clock is not None
        cur = [b for b in self.minute.get(symbol, []) if b.t <= self.clock]
        if not cur:
            raise LookupError(f"no {symbol} bar at or before {self.clock:%H:%M}")
        b = cur[-1]
        return (b.o if b.t == self.clock else b.c), 0.0   # at a bar boundary the quote is that bar's open

    def daily_bars(self, symbol: str, n: int) -> list[Bar]:
        return self.daily[symbol][-n:]


def minutes_of(day: datetime, start_mod: int = OPEN_MIN, end_mod: int = CLOSE_MIN) -> list[datetime]:
    base = day.replace(hour=0, minute=0, second=0, microsecond=0)
    return [base + timedelta(minutes=m) for m in range(start_mod, end_mod + 1)]
