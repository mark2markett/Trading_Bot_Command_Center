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
