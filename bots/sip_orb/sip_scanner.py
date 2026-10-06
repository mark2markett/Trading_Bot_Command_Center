"""Authenticated SIP v1 snapshot for the completed 09:30–09:35 Eastern window.

SCANNER_SECRET is a dedicated machine credential. SIP_SYMBOLS explicitly opts into
an operator watchlist fallback; a valid empty scan stays empty. No credentials in URLs.
"""

from __future__ import annotations

import logging
import math
import os
import re
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

import httpx
from cc_sdk.intraday import ET, UniversePending

MIN_PRICE, MIN_AVG_VOL, MIN_ATR = 5.0, 1_000_000, 0.50
SYMBOL = re.compile(r"[A-Z][A-Z0-9.]{0,9}\Z")


def filter_rank(rows: list[dict[str, Any]], top_n: int) -> list[str]:
    eligible = []
    for row in rows:
        try:
            values = {key: float(row[key]) for key in ("price", "rvol", "atr14", "avg_vol")}
            symbol = str(row["symbol"]).upper()
            if (
                all(math.isfinite(v) for v in values.values())
                and SYMBOL.fullmatch(symbol)
                and values["price"] > MIN_PRICE
                and values["avg_vol"] >= MIN_AVG_VOL
                and values["atr14"] > MIN_ATR
                and values["rvol"] >= 0
            ):
                eligible.append({**values, "symbol": symbol})
        except (KeyError, TypeError, ValueError):
            continue
    ranked = sorted(eligible, key=lambda r: (-r["rvol"], r["symbol"]))
    return list(dict.fromkeys(r["symbol"] for r in ranked))[: max(0, min(top_n, 20))]


def parse_snapshot(data: Any, now: datetime, top_n: int = 20) -> list[str]:
    def invalid():
        raise RuntimeError("scanner snapshot failed validation")

    if now.tzinfo is None:
        invalid()
    now = now.astimezone(ET)
    if (
        not isinstance(data, dict)
        or type(data.get("version")) is not int
        or data["version"] != 1
        or data.get("status") != "ready"
    ):
        invalid()
    if data.get("session_date") != now.date().isoformat():
        invalid()
    times = {}
    try:
        for key in ("window_start", "window_end", "generated_at"):
            times[key] = datetime.fromisoformat(data[key].replace("Z", "+00:00"))
            if times[key].tzinfo is None:
                invalid()
    except (ValueError, KeyError, TypeError, AttributeError):
        invalid()
    start = now.replace(hour=9, minute=30, second=0, microsecond=0)
    end = start + timedelta(minutes=5)
    if times["window_start"] != start or times["window_end"] != end or now < end:
        invalid()
    generated = times["generated_at"]
    if generated < end or not -30 <= (now - generated).total_seconds() <= 300:
        invalid()
    coverage = data.get("coverage")
    if not isinstance(coverage, dict) or any(
        type(coverage.get(k)) is not int or coverage[k] < 0 for k in ("universe", "eligible", "observed", "excluded")
    ):
        invalid()
    if (
        coverage["observed"] != coverage["eligible"]
        or coverage["eligible"] > coverage["universe"]
        or coverage["excluded"] > coverage["universe"]
    ):
        invalid()
    exclusions = data.get("exclusions")
    if not isinstance(exclusions, list) or len(exclusions) != coverage["excluded"]:
        invalid()
    if any(
        not isinstance(r, dict)
        or not isinstance(r.get("symbol"), str)
        or not SYMBOL.fullmatch(r["symbol"])
        or not isinstance(r.get("reason"), str)
        for r in exclusions
    ):
        invalid()
    rows = data.get("candidates")
    if not isinstance(rows, list) or len(rows) > 20 or len(rows) > coverage["observed"]:
        invalid()
    symbols = set()
    for row in rows:
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("symbol"), str)
            or not SYMBOL.fullmatch(row["symbol"])
            or row["symbol"] in symbols
        ):
            invalid()
        for key in ("price", "rvol", "atr14", "avg_vol"):
            if type(row.get(key)) not in (int, float) or not math.isfinite(row[key]) or row[key] < 0:
                invalid()
        symbols.add(row["symbol"])
    return filter_rank(rows, top_n)


def fetch(url: str, timeout: float = 10.0) -> dict[str, Any]:
    parsed = urlsplit(url)
    loopback = parsed.hostname in ("127.0.0.1", "localhost", "::1")
    if (
        (parsed.scheme != "https" and not (parsed.scheme == "http" and loopback))
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise RuntimeError("scanner URL must use HTTPS without embedded credentials")
    secret = os.getenv("SCANNER_SECRET", "")
    if len(secret) < 32:
        raise RuntimeError("SCANNER_SECRET must contain at least 32 characters")
    try:
        response = httpx.get(
            url,
            timeout=timeout,
            follow_redirects=False,
            headers={"Accept": "application/json", "Authorization": f"Bearer {secret}"},
        )
        if response.status_code in (202, 429) or response.status_code >= 500:
            raise UniversePending("SCANNER_PENDING")
        if response.status_code != 200:
            raise RuntimeError(f"scanner HTTP {response.status_code}")
        return response.json()
    except httpx.RequestError:
        raise UniversePending("SCANNER_TRANSPORT") from None
    except ValueError:
        raise RuntimeError("scanner JSON invalid") from None


def universe(now: datetime, top_n: int = 20, report=None) -> list[str]:
    now = now or datetime.now(ET)
    url = os.getenv("SCANNER_URL", "").strip()
    fallback = list(dict.fromkeys(s.strip() for s in os.getenv("SIP_SYMBOLS", "").upper().split(",") if s.strip()))[
        : min(top_n, 20)
    ]
    if any(not SYMBOL.fullmatch(s) for s in fallback):
        raise RuntimeError("SIP_SYMBOLS contains invalid symbols")
    log = logging.getLogger("sip_scanner")

    def record(action, reason, **details):
        log.info("%s: %s", action, reason)
        if report:
            report(details, action, reason)

    if url:
        try:
            data = fetch(url)
            syms = parse_snapshot(data, now, top_n)
            record(
                "SCANNER",
                f"candidates={len(data['candidates'])} selected={len(syms)}",
                candidates=len(data["candidates"]),
                selected=len(syms),
                session_date=data["session_date"],
                generated_at=data["generated_at"],
                coverage=data["coverage"],
            )
            return syms
        except UniversePending:
            record("SCANNER_PENDING", "scanner snapshot pending; retry next poll")
            if not fallback:
                raise
        except Exception as error:  # noqa: BLE001 — errors must never include credentials or upstream payloads
            record("SCANNER_ERROR", f"scanner request failed ({type(error).__name__})", error_type=type(error).__name__)
            if not fallback:
                raise RuntimeError(f"scanner request failed ({type(error).__name__}); no SIP_SYMBOLS fallback") from None
    elif not fallback:
        raise RuntimeError("SCANNER_URL and SIP_SYMBOLS are both unconfigured")
    record("SCANNER_FALLBACK", f"operator fixed watchlist selected={len(fallback)}", selected=len(fallback))
    return fallback
