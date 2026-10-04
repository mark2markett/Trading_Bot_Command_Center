"""M7.1 — OCC symbols, contract multiplier, Schwab chain parsing, and the chain call through the session."""
from datetime import date
from pathlib import Path

import httpx
import pytest

from cc_sdk.options import CONTRACT_MULTIPLIER, OptionQuote, contract_multiplier, is_occ, occ_symbol, parse_schwab_chain
from cc_sdk.schwab_feed import SchwabFeed, _BrokerSession


def test_occ_symbol_round_trip_and_multiplier():
    s = occ_symbol("SPY", date(2026, 10, 9), "C", 570.0)
    assert s == "SPY   261009C00570000" and is_occ(s)
    assert occ_symbol("QQQ", date(2026, 10, 9), "P", 482.5) == "QQQ   261009P00482500"
    assert contract_multiplier(s) == CONTRACT_MULTIPLIER == 100
    assert contract_multiplier("SPY") == 1 and not is_occ("SPY")
    with pytest.raises(ValueError):
        occ_symbol("SPY", date(2026, 10, 9), "X", 570)


def _contract(occ, put_call, strike, bid, ask, *, delta=0.5, vol=18.5, dte=5):
    return {"putCall": put_call, "symbol": occ, "bid": bid, "ask": ask, "mark": (bid + ask) / 2, "delta": delta,
            "theta": -0.21, "volatility": vol, "openInterest": 1200, "totalVolume": 340, "quoteTimeInLong": 1791000000000,
            "strikePrice": strike, "daysToExpiration": dte, "multiplier": 100.0}


CHAIN = {
    "symbol": "SPY", "status": "SUCCESS", "underlyingPrice": 570.4,
    "callExpDateMap": {"2026-10-09:5": {
        "570.0": [_contract("SPY   261009C00570000", "CALL", 570.0, 3.10, 3.16)],
        "575.0": [_contract("SPY   261009C00575000", "CALL", 575.0, 1.02, 1.06, delta=0.27)]}},
    "putExpDateMap": {"2026-10-09:5": {
        "570.0": [_contract("SPY   261009P00570000", "PUT", 570.0, 2.70, 2.75, delta=-0.49, vol=-999.0)]}},
}


def test_parse_schwab_chain():
    qs = parse_schwab_chain(CHAIN)
    assert [q.occ for q in qs] == ["SPY   261009C00570000", "SPY   261009C00575000", "SPY   261009P00570000"]
    c = qs[0]
    assert isinstance(c, OptionQuote) and c.underlying == "SPY" and c.expiry == date(2026, 10, 9) and c.right == "C"
    assert c.strike == 570.0 and c.iv == pytest.approx(0.185) and c.dte == 5 and c.quote_time == 1791000000.0
    assert c.mid == pytest.approx(3.13) and c.spread == pytest.approx(0.06)
    assert qs[2].iv is None            # Schwab's -999 means "not computed", never a real -999% vol
    assert parse_schwab_chain({"symbol": "SPY"}) == []


def test_chain_through_session_is_read_only(tmp_path, monkeypatch):
    monkeypatch.setenv("CC_VAR", str(tmp_path))
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.host == "m2m.test":
            return httpx.Response(200, json={"access_token": "A" * 40, "expires_at": "2099-01-01T00:00:00Z"})
        seen.append((req.method, req.url.path, dict(req.url.params)))
        return httpx.Response(200, json=CHAIN)

    sess = _BrokerSession("https://m2m.test/api/internal/schwab/access-token", "s" * 40, Path("gap_go_spread_bot"),
                          transport=httpx.MockTransport(handler))
    qs = SchwabFeed(sess).chain("SPY", date(2026, 10, 6), date(2026, 10, 13), strike_count=20)
    assert len(qs) == 3
    method, path, params = seen[0]
    assert method == "GET" and path == "/marketdata/v1/chains"
    assert params["symbol"] == "SPY" and params["contractType"] == "ALL"
    assert params["fromDate"] == "2026-10-06" and params["toDate"] == "2026-10-13" and params["strikeCount"] == "20"
