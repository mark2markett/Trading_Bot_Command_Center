"""Universe source for stocks in play. Primary: the M2M scanner over HTTP. Fallback: a fixed SIP_SYMBOLS list.

Contract for SCANNER_URL (GET, JSON): a list of objects with at least
    {"symbol": "ABCD", "price": 12.3, "rvol": 3.4, "atr14": 0.9, "avg_vol": 2500000}
rvol = volume in the first 5 minutes today ÷ 14-day average volume in the same 5 minutes. Objects missing a field are
dropped. Any wrapper object with a "candidates" or "data" key holding that list is accepted too.
Filters (paper, from the paper): price > $5, avg_vol ≥ 1M, atr14 > $0.50, then top N by rvol."""
from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any

MIN_PRICE, MIN_AVG_VOL, MIN_ATR = 5.0, 1_000_000, 0.50


def filter_rank(rows: list[dict[str, Any]], top_n: int) -> list[str]:
    ok = []
    for r in rows:
        try:
            if float(r["price"]) > MIN_PRICE and float(r["avg_vol"]) >= MIN_AVG_VOL and float(r["atr14"]) > MIN_ATR:
                ok.append((float(r["rvol"]), str(r["symbol"]).upper()))
        except (KeyError, TypeError, ValueError):
            continue
    ok.sort(reverse=True)
    out: list[str] = []
    for _, s in ok:
        if s not in out:
            out.append(s)
    return out[:top_n]


def fetch(url: str, timeout: float = 10.0) -> list[dict[str, Any]]:
    import httpx

    r = httpx.get(url, timeout=timeout, headers={"Accept": "application/json"})
    r.raise_for_status()
    data = r.json()
    if isinstance(data, dict):
        data = data.get("candidates") or data.get("data") or []
    return list(data)


def universe(now: datetime, top_n: int = 20, report=None) -> list[str]:
    url = os.getenv("SCANNER_URL", "").strip()
    fallback = [s.strip() for s in os.getenv("SIP_SYMBOLS", "").upper().split(",") if s.strip()][:top_n]
    log = logging.getLogger("sip_scanner")
    def record(action, reason, **details):
        log.info("%s: %s", action, reason)
        if report:
            report(details, action, reason)
    if url:
        try:
            rows = fetch(url)
            syms = filter_rank(rows, top_n)
            record("SCANNER", f"candidates={len(rows)} selected={len(syms)}", candidates=len(rows), selected=len(syms))
            if syms:
                return syms
        except Exception as e:  # noqa: BLE001
            record("SCANNER_ERROR", f"scanner request failed ({type(e).__name__})", error_type=type(e).__name__)
            if not fallback:
                raise RuntimeError(f"scanner request failed ({type(e).__name__}); no SIP_SYMBOLS fallback") from None
    elif not fallback:
        raise RuntimeError("SCANNER_URL and SIP_SYMBOLS are both unconfigured")
    if fallback:
        record("SCANNER_FALLBACK", f"fixed fallback selected={len(fallback)}", selected=len(fallback))
    return fallback
