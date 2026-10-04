"""M7.3 — paper fills for option legs and spreads (always against us; all-or-none), and spread P&L at x100."""
from datetime import date

import pytest

from cc_sdk.options import OptionQuote, fill_spread, paper_fill_price, spread_pnl

NOW = 1_791_000_100.0


def q(occ="SPY   261009C00570000", bid=3.10, ask=3.16, t=NOW - 5, right="C", strike=570.0):
    return OptionQuote(occ=occ, underlying="SPY", expiry=date(2026, 10, 9), strike=strike, right=right, bid=bid, ask=ask,
                       mark=(bid + ask) / 2, delta=0.5, theta=-0.2, iv=0.18, oi=1000, volume=100, quote_time=t, dte=5)


def test_buy_fills_above_mid_sell_below():
    px, why = paper_fill_price(q(), buying=True, now=NOW)
    assert why is None and px == pytest.approx(3.145)        # mid 3.13 + 25% of 0.06
    px, why = paper_fill_price(q(), buying=False, now=NOW)
    assert why is None and px == pytest.approx(3.115)        # mid 3.13 - 25% of 0.06


@pytest.mark.parametrize("kw,needle", [
    ({"bid": 0.0, "ask": 0.05}, "zero bid"),
    ({"bid": 3.20, "ask": 3.10}, "crossed"),
    ({"bid": 3.10, "ask": 3.10}, "crossed"),
    ({"bid": 0.80, "ask": 1.20}, "wide"),                    # 0.40 / 1.00 = 40% of mid
    ({"t": NOW - 200}, "old"),
])
def test_refuses_bad_quotes(kw, needle):
    px, why = paper_fill_price(q(**kw), buying=True, now=NOW, max_age_s=90)
    assert px is None and needle in why


def test_spread_fills_all_or_none():
    lo = q("SPY   261009C00570000", 3.10, 3.16)
    hi = q("SPY   261009C00575000", 1.02, 1.06, strike=575.0)
    f = fill_spread([(lo, True), (hi, False)], now=NOW)
    assert f.ok and f.prices == pytest.approx([3.145, 1.03]) and f.net_debit == pytest.approx(2.115)
    bad_hi = q("SPY   261009C00575000", 1.02, 1.06, t=NOW - 500, strike=575.0)
    f2 = fill_spread([(lo, True), (bad_hi, False)], now=NOW, max_age_s=90)
    assert not f2.ok and f2.prices == [] and "575" in f2.reason and "old" in f2.reason


def test_spread_pnl_applies_contract_multiplier():
    # long call bought 3.145, short call sold 1.03; closed at 4.00 / 1.50; 3 spreads
    pnl = spread_pnl(entry=[3.145, 1.03], exit=[4.00, 1.50], signs=[+1, -1], qty=3)
    assert pnl == pytest.approx(((4.00 - 3.145) - (1.50 - 1.03)) * 3 * 100)   # = $115.50
