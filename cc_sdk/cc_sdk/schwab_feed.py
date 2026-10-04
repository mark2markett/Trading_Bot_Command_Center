"""Schwab market-data feed for intraday bots — brokered access tokens, no OAuth on this machine.

The fleet never holds a Schwab refresh token or the app's Client Secret. M2M (the Vercel app that owns the weekly
Schwab re-authorization) exposes `GET /api/internal/schwab/access-token`; this module asks it for a 30-minute ACCESS
token when needed and calls Schwab's market-data API directly over httpx. Only M2M ever refreshes, so there is no
rotation race between two systems (Schwab rotates the refresh token on refresh — the M6.7 "share the refresh token"
design died on exactly that, `invalid_grant`, 2026-10-03).

Env (read from the bot folder's .env / .env.local): CC_TOKEN_BROKER_URL, CC_TOKEN_BROKER_SECRET.
Design: m2m-platform docs/SCHWAB-ACCESS-TOKEN-BROKER-SPEC-2026-10-03.md (PR-A = broker route, PR-B = this file).

Data only. `_BrokerSession` implements exactly the three market-data reads the feed and the research dump use and
NOTHING on /trader/v1 (accounts, orders, transactions). That absence is pinned by cc_sdk/tests/test_schwab_feed.py.
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from .intraday import ET, Bar
from .ledger import token_path

SCHWAB_API = "https://api.schwabapi.com"
REFRESH_EARLY_S = 60          # ask the broker for a new token this many seconds before the current one expires
BROKER_TIMEOUT_S = 15.0
SCHWAB_TIMEOUT_S = 20.0


class BrokerError(RuntimeError):
    """The broker refused or could not mint a token. The message never contains a credential."""


class _BrokerSession:
    """httpx session that injects a brokered Schwab access token and knows three market-data calls.

    - One in-flight token fetch per process (lock); every caller shares it.
    - Refreshes REFRESH_EARLY_S before `expires_at`.
    - On a Schwab 401, drops the token and re-fetches ONCE, then surfaces whatever comes back.
    - Writes the non-secret sidecar `<token_path>.issued` from the broker's `refresh_issued_at` so the dashboard's
      days-left chip keeps working; never writes a token file.
    """

    def __init__(self, broker_url: str, secret: str, bot_dir: Path, *, transport: httpx.BaseTransport | None = None):
        self._broker_url = broker_url
        self._secret = secret
        self._bot = bot_dir.name
        self._http = httpx.Client(transport=transport, timeout=SCHWAB_TIMEOUT_S)
        self._broker_http = httpx.Client(transport=transport, timeout=BROKER_TIMEOUT_S)
        self._lock = threading.Lock()
        self._access: str | None = None
        self._expires_at = 0.0
        self.broker_fetches = 0   # observability for tests and `check`

    # ---- token ----
    def _needs_token(self) -> bool:
        return self._access is None or time.time() >= self._expires_at - REFRESH_EARLY_S

    def _fetch_token(self) -> None:
        r = self._broker_http.get(self._broker_url, headers={"Authorization": f"Bearer {self._secret}", "X-CC-Bot": self._bot})
        self.broker_fetches += 1
        if r.status_code == 404:
            raise BrokerError("token broker is disabled on M2M (SCHWAB_TOKEN_BROKER_ENABLED is off) — the fleet fails closed")
        if r.status_code == 401:
            raise BrokerError("token broker rejected CC_TOKEN_BROKER_SECRET")
        if r.status_code == 429:
            raise BrokerError(f"token broker rate-limited the fleet; retry after {r.headers.get('retry-after', '?')} s")
        if r.status_code == 503:
            kind = (r.json().get("kind") if "json" in r.headers.get("content-type", "") else None) or "unknown"
            raise BrokerError(f"M2M could not refresh with Schwab (kind={kind}); check M2M's schwab-health-check")
        if r.status_code != 200:
            raise BrokerError(f"token broker returned HTTP {r.status_code}")
        body = r.json()
        tok = body.get("access_token")
        if not isinstance(tok, str) or len(tok) < 20:
            raise BrokerError("token broker response had no usable access_token")
        self._access = tok
        self._expires_at = _parse_iso(body.get("expires_at")) or (time.time() + 25 * 60)
        issued = _parse_iso(body.get("refresh_issued_at"))
        if issued:
            write_issued_sidecar(int(issued))

    def access_token(self) -> str:
        if not self._needs_token():
            return self._access  # type: ignore[return-value]
        with self._lock:
            if self._needs_token():
                self._fetch_token()
        return self._access  # type: ignore[return-value]

    def _invalidate(self) -> None:
        with self._lock:
            self._access, self._expires_at = None, 0.0

    # ---- transport ----
    def _get(self, path: str, params: dict) -> httpx.Response:
        r = self._http.get(SCHWAB_API + path, params=params, headers={"Authorization": f"Bearer {self.access_token()}"})
        if r.status_code != 401:
            return r
        self._invalidate()   # Schwab revoked or expired it early: one re-fetch, then surface whatever comes back
        return self._http.get(SCHWAB_API + path, params=params, headers={"Authorization": f"Bearer {self.access_token()}"})

    # ---- the three market-data reads (schwab-py-compatible signatures) ----
    def get_quote(self, symbol: str) -> httpx.Response:
        return self._get(f"/marketdata/v1/{symbol}/quotes", {"fields": "quote"})

    def get_price_history_every_minute(self, symbol: str, *, start_datetime: datetime, end_datetime: datetime,
                                       need_extended_hours_data: bool = False) -> httpx.Response:
        return self._get("/marketdata/v1/pricehistory", {
            "symbol": symbol, "periodType": "day", "frequencyType": "minute", "frequency": 1,
            "startDate": _ms(start_datetime), "endDate": _ms(end_datetime),
            "needExtendedHoursData": "true" if need_extended_hours_data else "false"})

    def get_price_history_every_day(self, symbol: str, *, start_datetime: datetime, end_datetime: datetime,
                                    need_extended_hours_data: bool = False) -> httpx.Response:
        return self._get("/marketdata/v1/pricehistory", {
            "symbol": symbol, "periodType": "month", "frequencyType": "daily", "frequency": 1,
            "startDate": _ms(start_datetime), "endDate": _ms(end_datetime),
            "needExtendedHoursData": "true" if need_extended_hours_data else "false"})


def _ms(t: datetime) -> int:
    if t.tzinfo is None:
        t = t.replace(tzinfo=ET)
    return int(t.timestamp() * 1000)


def _parse_iso(s: object) -> float | None:
    if not isinstance(s, str) or not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


class SchwabFeed:
    def __init__(self, client):
        self.c = client
        self._cache: dict[tuple[str, str], tuple[float, list[Bar]]] = {}

    @classmethod
    def from_broker(cls, bot_dir: Path, *, transport: httpx.BaseTransport | None = None) -> SchwabFeed:
        """Build the feed from CC_TOKEN_BROKER_URL / CC_TOKEN_BROKER_SECRET (bot .env / .env.local). No Schwab login here."""
        url, secret = os.getenv("CC_TOKEN_BROKER_URL", "").strip(), os.getenv("CC_TOKEN_BROKER_SECRET", "").strip()
        missing = [k for k, v in (("CC_TOKEN_BROKER_URL", url), ("CC_TOKEN_BROKER_SECRET", secret)) if not v]
        if missing:
            raise RuntimeError(f"broker config missing: {', '.join(missing)} — put them in this bot's .env.local; "
                               "the fleet never holds Schwab credentials itself")
        if not url.startswith("https://"):
            raise RuntimeError("CC_TOKEN_BROKER_URL must be https://")
        if len(secret) < 32:
            raise RuntimeError(f"CC_TOKEN_BROKER_SECRET is {len(secret)} chars; the broker refuses secrets under 32")
        return cls(_BrokerSession(url, secret, bot_dir, transport=transport))

    def check(self, symbol: str = "SPY") -> dict:
        """Prove the brokered token works: one quote, one minute-bar count. Prints nothing secret."""
        px, age = self.quote(symbol)
        bars = self.minute_bars(symbol, datetime.now(ET))
        out = {"symbol": symbol, "last": px, "quote_age_s": round(age, 1), "minute_bars_today": len(bars)}
        if isinstance(self.c, _BrokerSession):
            out["broker_url"] = self.c._broker_url
            out["broker_fetches"] = self.c.broker_fetches
        return out

    @staticmethod
    def _bars(data: dict) -> list[Bar]:
        out = []
        for c in data.get("candles", []):
            t = datetime.fromtimestamp(c["datetime"] / 1000, tz=ET)
            out.append(Bar(t, float(c["open"]), float(c["high"]), float(c["low"]), float(c["close"]), float(c["volume"])))
        return out

    def minute_bars(self, symbol: str, day: datetime) -> list[Bar]:
        key = (symbol, day.strftime("%Y-%m-%d"))
        hit = self._cache.get(key)
        if hit and time.time() - hit[0] < 10:          # the runner polls every 15 s; don't hammer the API per symbol
            return hit[1]
        start = day.replace(hour=9, minute=30, second=0, microsecond=0)
        r = self.c.get_price_history_every_minute(symbol, start_datetime=start, end_datetime=start + timedelta(hours=7),
                                                  need_extended_hours_data=False)
        r.raise_for_status()
        bars = [b for b in self._bars(r.json()) if 570 <= b.mod < 960]
        self._cache[key] = (time.time(), bars)
        return bars

    def quote(self, symbol: str) -> tuple[float, float]:
        r = self.c.get_quote(symbol)
        r.raise_for_status()
        q = r.json()[symbol]["quote"]
        age = max(0.0, time.time() - q.get("quoteTime", time.time() * 1000) / 1000)
        return float(q["lastPrice"]), age

    def daily_bars(self, symbol: str, n: int) -> list[Bar]:
        end = datetime.now(ET)
        r = self.c.get_price_history_every_day(symbol, start_datetime=end - timedelta(days=int(n * 1.6) + 20), end_datetime=end,
                                               need_extended_hours_data=False)
        r.raise_for_status()
        return self._bars(r.json())[-n:]


def write_issued_sidecar(created_ts: int) -> None:
    """Record when M2M's refresh token was issued, in a file that holds no secret, so the server can show days-left.
    Written next to where the fleet token file used to live (var/schwab_token.json.issued); no token file is written."""
    tp = token_path()
    tp.parent.mkdir(parents=True, exist_ok=True)
    Path(str(tp) + ".issued").write_text(json.dumps({"creation_timestamp": int(created_ts)}))


def issued_at_utc() -> datetime | None:
    """Read the sidecar back (dashboard helper)."""
    side = Path(str(token_path()) + ".issued")
    try:
        return datetime.fromtimestamp(int(json.loads(side.read_text())["creation_timestamp"]), tz=timezone.utc)
    except Exception:  # noqa: BLE001
        return None
