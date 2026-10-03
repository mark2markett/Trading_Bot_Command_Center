"""Schwab market-data feed for intraday bots (schwab-py). Data only — orders stay in each bot's broker layer.
Env: SCHWAB_API_KEY, SCHWAB_APP_SECRET, SCHWAB_CALLBACK_URL, TOKEN_PATH (relative to the bot folder)."""
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta
from pathlib import Path

from .intraday import ET, Bar
from .ledger import token_path


class SchwabFeed:
    def __init__(self, client):
        self.c = client
        self._cache: dict[tuple[str, str], tuple[float, list[Bar]]] = {}

    @classmethod
    def from_env(cls, bot_dir: Path) -> SchwabFeed:
        missing = [k for k in ("SCHWAB_API_KEY", "SCHWAB_APP_SECRET", "SCHWAB_CALLBACK_URL") if not os.getenv(k)]
        if missing:
            raise RuntimeError(f"Schwab credentials missing: {', '.join(missing)} (see .env.example)")
        key, sec = os.environ["SCHWAB_API_KEY"], os.environ["SCHWAB_APP_SECRET"]
        # Schwab app keys are typically 32 chars and secrets 16; the portal labels them Client ID / Client Secret.
        # Refuse only values that cannot be a Schwab pair (e.g. a 140-char token or a one-char typo); warn otherwise.
        if not (20 <= len(key) <= 64) or not (8 <= len(sec) <= 64):
            raise RuntimeError(f"SCHWAB_API_KEY is {len(key)} chars and SCHWAB_APP_SECRET is {len(sec)}; a Schwab Client ID/App Key is ~32 "
                               "and its Client Secret ~16. These look like values from somewhere else (see .env.example).")
        if len(key) != 32 or len(sec) != 16:
            print(f"note: key is {len(key)} chars and secret {len(sec)} (expected ~32/~16); trying anyway", file=__import__("sys").stderr)
        try:
            from schwab.auth import easy_client  # lazy: paper replays need no schwab-py
        except ImportError as e:
            raise RuntimeError("schwab-py is not installed in this environment: pip install schwab-py") from e
        tp = token_path(bot_dir)
        tp.parent.mkdir(parents=True, exist_ok=True)
        client = easy_client(api_key=key, app_secret=sec, callback_url=os.environ["SCHWAB_CALLBACK_URL"], token_path=str(tp))
        write_issued_sidecar(tp)
        return cls(client)

    @classmethod
    def from_refresh_token(cls, bot_dir: Path, refresh_token: str, issued_at: datetime | None = None) -> SchwabFeed:
        """Adopt a refresh token minted elsewhere (M2M's weekly login). Schwab does not rotate refresh tokens on use, so
        two systems can share one. Writes the shared token file in schwab-py's format with an expired access token; the
        first request refreshes it using the Client ID/Secret. Never prints the token."""
        import json

        for k in ("SCHWAB_API_KEY", "SCHWAB_APP_SECRET"):
            if not os.getenv(k):
                raise RuntimeError(f"{k} missing: the refresh token is only usable together with the app's Client ID and Client Secret")
        refresh_token = refresh_token.strip()
        if len(refresh_token) < 100:
            raise RuntimeError(f"refresh token is {len(refresh_token)} chars; expected ~140. If you pasted at the hidden prompt and it "
                               "arrived truncated, set $env:SCHWAB_REFRESH_TOKEN in the same PowerShell session and rerun.")
        issued = issued_at or datetime.now(ET)
        tp = token_path(bot_dir)
        tp.parent.mkdir(parents=True, exist_ok=True)
        tp.write_text(json.dumps({"creation_timestamp": int(issued.timestamp()),
                                  "token": {"access_token": "", "refresh_token": refresh_token, "token_type": "Bearer", "scope": "api",
                                            "expires_in": 1800, "expires_at": 1}}))
        write_issued_sidecar(tp)
        return cls.from_env(bot_dir)

    def check(self, symbol: str = "SPY") -> dict:
        """Prove the token works: one quote, one minute-bar count. Prints nothing secret."""
        px, age = self.quote(symbol)
        bars = self.minute_bars(symbol, datetime.now(ET))
        return {"symbol": symbol, "last": px, "quote_age_s": round(age, 1), "minute_bars_today": len(bars), "token_file": str(token_path())}

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


def write_issued_sidecar(tp: Path) -> None:
    """Record when the refresh token was issued, in a file that holds no secret, so the server can show days-left without
    reading the token and without being fooled by schwab-py rewriting the token file on every access-token refresh."""
    import json

    try:
        created = json.loads(tp.read_text()).get("creation_timestamp")
    except Exception:  # noqa: BLE001
        return
    if created:
        Path(str(tp) + ".issued").write_text(json.dumps({"creation_timestamp": int(created)}))
