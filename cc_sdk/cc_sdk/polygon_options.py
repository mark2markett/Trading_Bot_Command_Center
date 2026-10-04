"""Real-time option quotes from Polygon (owner decision 2026-10-04: "use Polygon's real time options data not Schwab
options data - use schwab for all else"; recorded in docs/DECISIONS.md M7).

`PolygonOptions.snapshot()` reads `/v3/snapshot/options/{underlying}` (read-only, paginated) into the same
`OptionQuote` the rest of the SDK uses, with OCC symbols normalised to the space-padded form positions are keyed by.
`MixedFeed` is what an options bot runs on: underlying quotes, minute bars and daily bars from Schwab; option chains
from Polygon. Nothing here places an order. Errors never include the API key or a response body.
Env: POLYGON_API_KEY (command-center root .env.local).
"""
from __future__ import annotations

import os
import re
from datetime import date, datetime
from typing import Any

import httpx

from .intraday import ET
from .options import OptionQuote, occ_symbol

BASE = "https://api.polygon.io"
MAX_PAGES = 20
STRIKE_BAND = 0.05            # chain(): strikes within +/-5% of the Schwab underlying price
_TICKER = re.compile(r"^O:(?P<root>[A-Z.]+?)(?P<ymd>\d{6})(?P<right>[CP])(?P<strike>\d{8})$")


def _f(v: Any) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def parse_polygon_snapshot(results: list[dict[str, Any]], underlying: str, today: date | None = None) -> list[OptionQuote]:
    today = today or datetime.now(ET).date()
    out: list[OptionQuote] = []
    for c in results or []:
        m = _TICKER.match(str((c.get("details") or {}).get("ticker") or ""))
        q = c.get("last_quote") or {}
        if not m or "bid" not in q or "ask" not in q:
            continue
        ymd = m["ymd"]
        expiry = date(2000 + int(ymd[:2]), int(ymd[2:4]), int(ymd[4:]))
        strike = int(m["strike"]) / 1000.0
        greeks = c.get("greeks") or {}
        bid, ask = float(q.get("bid") or 0.0), float(q.get("ask") or 0.0)
        out.append(OptionQuote(
            occ=occ_symbol(m["root"], expiry, m["right"], strike), underlying=underlying.upper(), expiry=expiry, strike=strike,
            right=m["right"], bid=bid, ask=ask, mark=float(q.get("midpoint") or (bid + ask) / 2),
            delta=_f(greeks.get("delta")), theta=_f(greeks.get("theta")), iv=_f(c.get("implied_volatility")),
            oi=int(c.get("open_interest") or 0), volume=int((c.get("day") or {}).get("volume") or 0),
            quote_time=float(q.get("last_updated") or 0) / 1e9, dte=(expiry - today).days))
    return sorted(out, key=lambda x: (x.expiry, x.right, x.strike))


class PolygonOptions:
    def __init__(self, api_key: str, *, transport: httpx.BaseTransport | None = None, max_pages: int = MAX_PAGES):
        if not api_key.strip():
            raise RuntimeError("POLYGON_API_KEY missing — put it in the command-center root .env.local")
        self._headers = {"Authorization": f"Bearer {api_key.strip()}"}
        self._http = httpx.Client(transport=transport, timeout=20.0)
        self.max_pages = max_pages

    def snapshot(self, underlying: str, from_date: date, to_date: date, *, strike_gte: float | None = None,
                 strike_lte: float | None = None) -> list[OptionQuote]:
        params: dict[str, Any] = {"expiration_date.gte": from_date.isoformat(), "expiration_date.lte": to_date.isoformat(),
                                  "limit": 250}
        if strike_gte is not None:
            params["strike_price.gte"] = round(strike_gte, 2)
        if strike_lte is not None:
            params["strike_price.lte"] = round(strike_lte, 2)
        url: str | None = f"{BASE}/v3/snapshot/options/{underlying.upper()}"
        page_params: dict[str, Any] | None = params
        results: list[dict[str, Any]] = []
        for _ in range(self.max_pages):
            # Follow-up pages: next_url already carries its cursor and filters. Passing ANY params (even {}) makes
            # httpx replace the URL's query string and drop the cursor, which loops on page one.
            r = self._http.get(url, params=page_params, headers=self._headers)  # type: ignore[arg-type]
            if r.status_code != 200:
                raise RuntimeError(f"Polygon options snapshot HTTP {r.status_code}")
            body = r.json()
            results += body.get("results") or []
            url, page_params = body.get("next_url"), None
            if not url:
                break
        else:
            raise RuntimeError(f"Polygon options snapshot exceeded {self.max_pages} pages; narrow the strike band")
        return parse_polygon_snapshot(results, underlying)


def polygon_from_env(*, transport: httpx.BaseTransport | None = None) -> PolygonOptions:
    return PolygonOptions(os.getenv("POLYGON_API_KEY", ""), transport=transport)


class MixedFeed:
    """Schwab for the underlying (quotes, minute and daily bars); Polygon for option chains."""

    def __init__(self, schwab_feed: Any, polygon: PolygonOptions, *, strike_band: float = STRIKE_BAND):
        self.base, self.polygon, self.strike_band = schwab_feed, polygon, strike_band

    def quote(self, symbol: str) -> tuple[float, float]:
        return self.base.quote(symbol)

    def minute_bars(self, symbol: str, day: datetime) -> list:
        return self.base.minute_bars(symbol, day)

    def daily_bars(self, symbol: str, n: int) -> list:
        return self.base.daily_bars(symbol, n)

    def check(self, symbol: str = "SPY") -> dict:
        return {**self.base.check(symbol), "options_source": "polygon"}

    def chain(self, symbol: str, from_date: date, to_date: date, strike_count: int | None = None) -> list[OptionQuote]:
        spot, _ = self.base.quote(symbol)
        return self.polygon.snapshot(symbol, from_date, to_date, strike_gte=spot * (1 - self.strike_band),
                                     strike_lte=spot * (1 + self.strike_band))
