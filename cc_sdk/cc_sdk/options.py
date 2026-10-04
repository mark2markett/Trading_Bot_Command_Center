"""Options primitives for paper trading (M7, docs/06_OPTIONS_M7_SPEC.md).

Pure functions and small dataclasses only: OCC symbols, the contract multiplier, parsing Schwab's option chain, and
the paper fill model. Nothing here talks to a broker or places an order.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

CONTRACT_MULTIPLIER = 100
# OCC: root padded to 6, YYMMDD, C/P, strike × 1000 padded to 8. Schwab returns roots space-padded.
_OCC = re.compile(r"^(?P<root>[A-Z.]{1,6}) *(?P<ymd>\d{6})(?P<right>[CP])(?P<strike>\d{8})$")


def is_occ(symbol: str) -> bool:
    return bool(_OCC.match(symbol or ""))


def contract_multiplier(symbol: str) -> int:
    """100 for an OCC option symbol, 1 for anything else (shares)."""
    return CONTRACT_MULTIPLIER if is_occ(symbol) else 1


def occ_symbol(root: str, expiry: date, right: str, strike: float) -> str:
    """Schwab-style OCC symbol: root space-padded to 6 characters."""
    if right not in ("C", "P"):
        raise ValueError("right must be C or P")
    return f"{root.upper():<6}{expiry:%y%m%d}{right}{round(strike * 1000):08d}"


def parse_occ(symbol: str) -> tuple[str, date, str, float]:
    """(root, expiry, right, strike) from an OCC symbol."""
    m = _OCC.match(symbol or "")
    if not m:
        raise ValueError(f"not an OCC option symbol: {symbol!r}")
    ymd = m["ymd"]
    return m["root"], date(2000 + int(ymd[:2]), int(ymd[2:4]), int(ymd[4:])), m["right"], int(m["strike"]) / 1000.0


def intrinsic(symbol: str, underlying_px: float) -> float:
    """Per-share intrinsic value at a given underlying price (the floor value of an option)."""
    _, _, right, strike = parse_occ(symbol)
    return max(0.0, underlying_px - strike) if right == "C" else max(0.0, strike - underlying_px)


@dataclass(frozen=True)
class OptionQuote:
    occ: str
    underlying: str
    expiry: date
    strike: float
    right: str              # "C" | "P"
    bid: float
    ask: float
    mark: float
    delta: float | None
    theta: float | None
    iv: float | None        # decimal (0.18 = 18%)
    oi: int
    volume: int
    quote_time: float       # epoch seconds
    dte: int

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2

    @property
    def spread(self) -> float:
        return self.ask - self.bid


def _num(v: Any) -> float | None:
    """Schwab uses -999 / NaN for greeks it could not compute."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f or f <= -999:
        return None
    return f


def parse_schwab_chain(payload: dict[str, Any]) -> list[OptionQuote]:
    """Flatten Schwab's `/marketdata/v1/chains` response (callExpDateMap / putExpDateMap) into OptionQuotes."""
    under = str(payload.get("symbol") or "").upper()
    out: list[OptionQuote] = []
    for key, right in (("callExpDateMap", "C"), ("putExpDateMap", "P")):
        for exp_key, strikes in (payload.get(key) or {}).items():
            exp_date = date.fromisoformat(exp_key.split(":")[0])
            for contracts in (strikes or {}).values():
                for c in contracts or []:
                    occ = str(c.get("symbol") or "")
                    if not is_occ(occ):
                        continue
                    iv = _num(c.get("volatility"))
                    qt = c.get("quoteTimeInLong") or c.get("tradeTimeInLong") or 0
                    out.append(OptionQuote(
                        occ=occ, underlying=under, expiry=exp_date, strike=float(c.get("strikePrice")), right=right,
                        bid=float(c.get("bid") or 0.0), ask=float(c.get("ask") or 0.0), mark=float(c.get("mark") or 0.0),
                        delta=_num(c.get("delta")), theta=_num(c.get("theta")),
                        iv=(iv / 100.0) if iv is not None else None,
                        oi=int(c.get("openInterest") or 0), volume=int(c.get("totalVolume") or 0),
                        quote_time=float(qt) / 1000.0, dte=int(c.get("daysToExpiration") or 0)))
    return sorted(out, key=lambda q: (q.expiry, q.right, q.strike))


def now_epoch() -> float:
    return datetime.now(timezone.utc).timestamp()


# ---- paper fills (M7.3) -------------------------------------------------------------------------------------------
SLIP_FRAC = 0.25          # fill at mid +/- 25% of the bid-ask spread, always against us
MAX_SPREAD_PCT = 0.15     # refuse a leg whose bid-ask spread is wider than 15% of mid
MAX_QUOTE_AGE_S = 90.0


def paper_fill_price(q: OptionQuote, *, buying: bool, now: float | None = None, slip_frac: float = SLIP_FRAC,
                     max_spread_pct: float = MAX_SPREAD_PCT, max_age_s: float = MAX_QUOTE_AGE_S) -> tuple[float | None, str | None]:
    """(price per share, None) or (None, why it would not fill). Never fills on a zero bid, a crossed or locked
    market, a spread too wide to price honestly, or a stale quote."""
    now = now_epoch() if now is None else now
    if q.bid <= 0:
        return None, f"{q.occ.strip()}: zero bid"
    if q.ask <= q.bid:
        return None, f"{q.occ.strip()}: crossed or locked market ({q.bid:.2f}/{q.ask:.2f})"
    if q.spread / q.mid > max_spread_pct:
        return None, f"{q.occ.strip()}: spread too wide ({q.spread / q.mid:.0%} of mid > {max_spread_pct:.0%})"
    age = now - q.quote_time
    if age > max_age_s:
        return None, f"{q.occ.strip()}: quote {age:.0f}s old > {max_age_s:.0f}s"
    px = q.mid + slip_frac * q.spread if buying else q.mid - slip_frac * q.spread
    return round(px, 4), None


@dataclass
class SpreadFill:
    ok: bool
    prices: list[float]
    net_debit: float = 0.0
    reason: str = ""


def fill_spread(legs: list[tuple[OptionQuote, bool]], *, now: float | None = None, **kw: float) -> SpreadFill:
    """All-or-none: every leg must fill or none does. legs = [(quote, buying)]. net_debit = paid minus received."""
    prices: list[float] = []
    for quote, buying in legs:
        px, why = paper_fill_price(quote, buying=buying, now=now, **kw)
        if px is None:
            return SpreadFill(False, [], 0.0, f"spread not filled: {why}")
        prices.append(px)
    net = sum(px if buying else -px for px, (_, buying) in zip(prices, legs, strict=True))
    return SpreadFill(True, prices, round(net, 4))


def spread_pnl(*, entry: list[float], exit: list[float], signs: list[int], qty: int) -> float:  # noqa: A002
    """Dollar P&L of `qty` spreads. signs: +1 long leg, -1 short leg. Prices are per share; x100 per contract."""
    per_share = sum(s * (x - e) for e, x, s in zip(entry, exit, signs, strict=True))
    return round(per_share * qty * CONTRACT_MULTIPLIER, 2)
