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
import sys
import threading
import time
from datetime import date, datetime, timedelta, timezone
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

    def get_option_chain(self, symbol: str, *, from_date: str, to_date: str, strike_count: int | None = None) -> httpx.Response:
        """Read-only market data (M7.1): calls and puts expiring between from_date and to_date (YYYY-MM-DD)."""
        params: dict = {"symbol": symbol, "contractType": "ALL", "fromDate": from_date, "toDate": to_date,
                        "includeUnderlyingQuote": "true"}
        if strike_count:
            params["strikeCount"] = strike_count
        return self._get("/marketdata/v1/chains", params)


class _SharedStateSession(_BrokerSession):
    """Same pattern as M2M and m2m-stock-intelligence: read the current refresh token from the shared Supabase row
    `scan_state.schwab_token_state` (written by the weekly re-auth at mark2markets.com/trades/schwab-reauth), exchange
    it at Schwab with the app's Client ID / Secret, and call market data directly. Nothing in M2M's deployment is used.

    Read-only toward M2M except in one case: if Schwab ever returns a DIFFERENT refresh token, it is written back so
    M2M and the other apps keep a valid login (that write is what the sister apps do too). Otherwise nothing is written.
    Env: SCHWAB_CLIENT_ID, SCHWAB_CLIENT_SECRET, SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY (command-center root .env.local).
    """

    TOKEN_URL = SCHWAB_API + "/v1/oauth/token"
    _SAFE_OAUTH = {"invalid_grant", "invalid_client", "unauthorized_client", "unsupported_token_type", "invalid_request"}

    def __init__(self, supabase_url: str, service_key: str, client_id: str, client_secret: str, bot_dir: Path,
                 *, transport: httpx.BaseTransport | None = None):
        super().__init__("shared-state", "", bot_dir, transport=transport)
        import base64

        self._rest = supabase_url.rstrip("/") + "/rest/v1/scan_state"
        self._db = {"apikey": service_key, "Authorization": f"Bearer {service_key}"}
        self._basic = {"Authorization": "Basic " + base64.b64encode(f"{client_id}:{client_secret}".encode()).decode(),
                       "Accept": "application/json"}

    def _read_state(self) -> dict:
        r = self._http.get(self._rest, params={"id": "eq.1", "select": "schwab_token_state"}, headers=self._db)
        if r.status_code != 200:
            raise BrokerError(f"shared Schwab token state unreadable (Supabase HTTP {r.status_code})")
        rows = r.json()
        state = rows[0].get("schwab_token_state") if isinstance(rows, list) and rows else None
        if not isinstance(state, dict) or not str(state.get("refresh_token") or "").strip():
            raise BrokerError("shared Schwab token state has no refresh token; run the re-auth at mark2markets.com/trades/schwab-reauth")
        return state

    def _fetch_token(self) -> None:
        state = self._read_state()
        used = str(state["refresh_token"]).strip()
        r = self._http.post(self.TOKEN_URL, headers=self._basic, data={"grant_type": "refresh_token", "refresh_token": used})
        self.broker_fetches += 1
        if r.status_code != 200:
            code = ""
            try:
                err = r.json().get("error")
                code = f", {err}" if err in self._SAFE_OAUTH else ""
            except Exception:  # noqa: BLE001
                pass
            raise BrokerError(f"Schwab refused the shared refresh token (HTTP {r.status_code}{code}); "
                              "run the re-auth at mark2markets.com/trades/schwab-reauth")
        body = r.json()
        tok = body.get("access_token")
        if not isinstance(tok, str) or len(tok) < 20:
            raise BrokerError("Schwab token response had no usable access_token")
        try:
            expires_in = float(body.get("expires_in") or 1800)
        except (TypeError, ValueError):
            expires_in = 1800.0
        self._access, self._expires_at = tok, time.time() + expires_in
        issued = _parse_iso(state.get("issued_at"))
        returned = body.get("refresh_token")
        if isinstance(returned, str) and returned.strip() and returned.strip() != used:
            issued = time.time()
            self._write_back(state, returned.strip())
        if issued:
            write_issued_sidecar(int(issued))

    def _write_back(self, state: dict, new_token: str) -> None:
        """Only on rotation, so M2M's stored login stays valid. Never fatal; never logs a value."""
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        nxt = {**state, "refresh_token": new_token, "issued_at": now, "last_refreshed_at": now}
        try:
            r = self._http.patch(self._rest, params={"id": "eq.1"}, json={"schwab_token_state": nxt},
                                 headers={**self._db, "Prefer": "return=minimal"})
            if r.status_code not in (200, 204):
                print(f"[schwab] rotated refresh token NOT saved (Supabase HTTP {r.status_code})", file=sys.stderr)
        except Exception as e:  # noqa: BLE001
            print(f"[schwab] rotated refresh token NOT saved ({type(e).__name__})", file=sys.stderr)


SHARED_VARS = ("SCHWAB_CLIENT_ID", "SCHWAB_CLIENT_SECRET", "SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY")
REPO_ROOT = Path(__file__).resolve().parents[2]


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

    @classmethod
    def connect(cls, bot_dir: Path, *, transport: httpx.BaseTransport | None = None) -> SchwabFeed:
        """Shared token state (like M2M's other apps) when its four variables are set; otherwise the broker.
        Loads the command-center root .env.local without overriding values the bot already set."""
        try:
            from dotenv import load_dotenv

            load_dotenv(REPO_ROOT / ".env.local", override=False)
        except ImportError:
            pass
        vals = {k: os.getenv(k, "").strip() for k in SHARED_VARS}
        if all(vals.values()):
            if not vals["SUPABASE_URL"].startswith("https://"):
                raise RuntimeError("SUPABASE_URL must be https://")
            return cls(_SharedStateSession(vals["SUPABASE_URL"], vals["SUPABASE_SERVICE_ROLE_KEY"], vals["SCHWAB_CLIENT_ID"],
                                           vals["SCHWAB_CLIENT_SECRET"], bot_dir, transport=transport))
        return cls.from_broker(bot_dir, transport=transport)

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

    def chain(self, symbol: str, from_date: date, to_date: date, strike_count: int | None = 40) -> list:
        """Option quotes for `symbol` expiring in [from_date, to_date], parsed into cc_sdk.options.OptionQuote."""
        from .options import parse_schwab_chain

        r = self.c.get_option_chain(symbol, from_date=from_date.isoformat(), to_date=to_date.isoformat(), strike_count=strike_count)
        r.raise_for_status()
        return parse_schwab_chain(r.json())

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
