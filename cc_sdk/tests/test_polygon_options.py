"""Polygon option chain source (owner decision 2026-10-04): parsing, pagination, strike band, errors without secrets."""
from datetime import date

import httpx
import pytest

from cc_sdk.polygon_options import MixedFeed, PolygonOptions, parse_polygon_snapshot

KEY = "p" * 32


def contract(ticker, ctype, exp, strike, bid, ask, *, delta=0.5, upd=1_791_000_000_000_000_000):
    return {"details": {"ticker": ticker, "contract_type": ctype, "expiration_date": exp, "strike_price": strike,
                        "shares_per_contract": 100},
            "last_quote": {"bid": bid, "ask": ask, "midpoint": (bid + ask) / 2, "last_updated": upd, "timeframe": "REAL-TIME"},
            "greeks": {"delta": delta, "theta": -0.2}, "implied_volatility": 0.17, "open_interest": 900, "day": {"volume": 50}}


PAGE1 = [contract("O:SPY261009C00770000", "call", "2026-10-09", 770, 4.10, 4.14)]
PAGE2 = [contract("O:SPY261009P00765000", "put", "2026-10-09", 765, 2.50, 2.54, delta=-0.4),
         {"details": {"ticker": "O:SPY261009C00775000"}}]          # no quote -> skipped


def test_parse_normalises_occ_and_units():
    qs = parse_polygon_snapshot(PAGE1 + PAGE2, "spy", today=date(2026, 10, 5))
    assert [q.occ for q in qs] == ["SPY   261009C00770000", "SPY   261009P00765000"]
    c = qs[0]
    assert (c.underlying, c.expiry, c.strike, c.right, c.dte) == ("SPY", date(2026, 10, 9), 770.0, "C", 4)
    assert c.mid == pytest.approx(4.12) and c.iv == pytest.approx(0.17) and c.quote_time == pytest.approx(1_791_000_000.0)


def test_snapshot_follows_pages_and_sends_key_in_header_only():
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        assert req.headers["authorization"] == f"Bearer {KEY}" and KEY not in str(req.url)
        if "cursor" in str(req.url):
            return httpx.Response(200, json={"status": "OK", "results": PAGE2})
        return httpx.Response(200, json={"status": "OK", "results": PAGE1,
                                         "next_url": "https://api.polygon.io/v3/snapshot/options/SPY?cursor=abc"})

    p = PolygonOptions(KEY, transport=httpx.MockTransport(handler))
    qs = p.snapshot("SPY", date(2026, 10, 7), date(2026, 10, 12), strike_gte=731.5, strike_lte=808.5)
    assert len(qs) == 2 and len(calls) == 2
    first = dict(calls[0].url.params)
    assert first["expiration_date.gte"] == "2026-10-07" and first["strike_price.gte"] == "731.5"


def test_errors_never_leak_key_or_body():
    p = PolygonOptions(KEY, transport=httpx.MockTransport(lambda r: httpx.Response(403, json={"message": KEY})))
    with pytest.raises(RuntimeError) as ei:
        p.snapshot("SPY", date(2026, 10, 7), date(2026, 10, 12))
    assert "HTTP 403" in str(ei.value) and KEY not in str(ei.value)
    with pytest.raises(RuntimeError, match="POLYGON_API_KEY"):
        PolygonOptions("  ")


def test_mixed_feed_uses_schwab_for_underlying_and_polygon_for_chain():
    class Schwab:
        def quote(self, s):
            return 770.0, 1.0

        def minute_bars(self, s, d):
            return ["bar"]

        def daily_bars(self, s, n):
            return ["day"] * n

        def check(self, s="SPY"):
            return {"symbol": s, "last": 770.0}

    seen = {}

    def handler(req):
        seen.update(dict(req.url.params))
        return httpx.Response(200, json={"status": "OK", "results": PAGE1})

    f = MixedFeed(Schwab(), PolygonOptions(KEY, transport=httpx.MockTransport(handler)))
    assert f.quote("SPY") == (770.0, 1.0) and f.minute_bars("SPY", None) == ["bar"] and len(f.daily_bars("SPY", 3)) == 3
    assert f.check()["options_source"] == "polygon"
    assert len(f.chain("SPY", date(2026, 10, 7), date(2026, 10, 12))) == 1
    assert float(seen["strike_price.gte"]) == pytest.approx(731.5) and float(seen["strike_price.lte"]) == pytest.approx(808.5)
