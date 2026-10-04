"""SchwabFeed + the brokered session (PR-B of m2m-platform docs/SCHWAB-ACCESS-TOKEN-BROKER-SPEC-2026-10-03.md).

No network: every HTTP call goes through httpx.MockTransport. Covers
- the M6.7 regression (methods must attach to the class),
- check()/minute_bars() against a fake client,
- the broker session: refresh-before-expiry, ONE in-flight fetch under concurrency, 401 → one re-fetch then raise,
  broker error mapping, sidecar written without any secret, and the absence of any trading method.
"""
import json
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from cc_sdk import schwab_feed
from cc_sdk.intraday import ET
from cc_sdk.schwab_feed import BrokerError, SchwabFeed, _BrokerSession

METHODS = ("check", "_bars", "minute_bars", "quote", "daily_bars")
BROKER = "https://m2m.test/api/internal/schwab/access-token"
SECRET = "s" * 40


def test_methods_attach_to_class():
    for name in METHODS:
        assert callable(getattr(SchwabFeed, name, None)), f"SchwabFeed.{name} missing — a module-level def slipped into the class body"
    assert callable(schwab_feed.write_issued_sidecar)
    assert not hasattr(SchwabFeed, "write_issued_sidecar")
    assert not hasattr(SchwabFeed, "from_env") and not hasattr(SchwabFeed, "from_refresh_token")


def test_broker_session_has_no_trading_surface():
    """Paper-only guarantee on the fleet side: no accounts / orders / transactions method exists to call."""
    names = {n for n in dir(_BrokerSession) if not n.startswith("__")}
    for banned in ("place_order", "cancel_order", "get_account", "get_accounts", "get_orders", "get_transactions",
                   "replace_order", "preview_order"):
        assert banned not in names
    assert {"get_quote", "get_price_history_every_minute", "get_price_history_every_day"} <= names


# ---- fake client (feed-level) ----
class _Resp:
    def __init__(self, payload):
        self._p = payload
        self.status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return self._p


class _FakeClient:
    def get_quote(self, symbol):
        return _Resp({symbol: {"quote": {"lastPrice": 567.89, "quoteTime": 0}}})

    def get_price_history_every_minute(self, symbol, start_datetime, end_datetime, need_extended_hours_data):
        base = start_datetime.replace(hour=9, minute=30, second=0, microsecond=0)
        candles = [{"datetime": int(base.replace(minute=30 + i).timestamp() * 1000), "open": 1, "high": 2, "low": 0.5,
                    "close": 1.5, "volume": 100} for i in range(2)]
        return _Resp({"candles": candles})


def test_check_runs_end_to_end_without_secrets():
    out = SchwabFeed(_FakeClient()).check("SPY")
    assert out == {"symbol": "SPY", "last": 567.89, "quote_age_s": out["quote_age_s"], "minute_bars_today": 2}
    assert "token" not in json.dumps(out).lower()


def test_minute_bars_filters_to_regular_hours():
    bars = SchwabFeed(_FakeClient()).minute_bars("SPY", datetime.now(ET))
    assert [b.mod for b in bars] == [570, 571]


# ---- broker session ----
class _World:
    """One MockTransport that plays both the broker and Schwab. Mutable so tests can script failures."""

    def __init__(self, *, expires_in_s=1800, broker_status=200, broker_delay_s=0.0, schwab_401_first=False):
        self.expires_in_s, self.broker_status, self.broker_delay_s = expires_in_s, broker_status, broker_delay_s
        self.schwab_401_first = schwab_401_first
        self.broker_calls, self.schwab_calls, self.auth_headers, self.bot_headers = 0, 0, [], []
        self.issued = datetime.now(timezone.utc) - timedelta(days=1)
        self.n = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        if str(request.url) == BROKER:
            self.broker_calls += 1
            self.bot_headers.append(request.headers.get("x-cc-bot"))
            if request.headers.get("authorization") != f"Bearer {SECRET}":
                return httpx.Response(401, json={"error": "Unauthorized"})
            time.sleep(self.broker_delay_s)
            if self.broker_status != 200:
                body = {"error": "schwab_refresh_failed", "kind": "auth"} if self.broker_status == 503 else {"error": "x"}
                return httpx.Response(self.broker_status, json=body, headers={"retry-after": "42"})
            self.n += 1
            exp = (datetime.now(timezone.utc) + timedelta(seconds=self.expires_in_s)).isoformat().replace("+00:00", "Z")
            return httpx.Response(200, json={"access_token": f"ACCESS-{self.n}-{'x' * 30}", "token_type": "Bearer",
                                             "expires_at": exp, "scope": "market-data-only",
                                             "refresh_issued_at": self.issued.isoformat().replace("+00:00", "Z"),
                                             "refresh_days_left": 6.0})
        assert request.url.host == "api.schwabapi.com"
        self.schwab_calls += 1
        self.auth_headers.append(request.headers.get("authorization"))
        if self.schwab_401_first and self.schwab_calls == 1:
            return httpx.Response(401, json={"error": "expired"})
        if request.url.path.endswith("/quotes"):
            sym = request.url.path.split("/")[-2]
            return httpx.Response(200, json={sym: {"quote": {"lastPrice": 100.5, "quoteTime": int(time.time() * 1000)}}})
        return httpx.Response(200, json={"candles": []})


@pytest.fixture
def var(tmp_path, monkeypatch):
    monkeypatch.setenv("CC_VAR", str(tmp_path))
    return tmp_path


def _session(world, bot="gap_go_bot"):
    return _BrokerSession(BROKER, SECRET, Path(bot), transport=httpx.MockTransport(world.handler))


def test_fetches_once_and_injects_bearer_and_bot_header(var):
    w = _World()
    s = _session(w)
    r1 = s.get_quote("SPY"); r2 = s.get_quote("QQQ")
    assert r1.status_code == 200 and r2.json()["QQQ"]["quote"]["lastPrice"] == 100.5
    assert w.broker_calls == 1 and w.schwab_calls == 2
    assert w.auth_headers == [f"Bearer ACCESS-1-{'x' * 30}"] * 2
    assert w.bot_headers == ["gap_go_bot"]


def test_refreshes_before_expiry(var):
    w = _World(expires_in_s=schwab_feed.REFRESH_EARLY_S - 5)   # already inside the early-refresh window
    s = _session(w)
    s.get_quote("SPY"); s.get_quote("SPY")
    assert w.broker_calls == 2


def test_single_inflight_fetch_under_concurrency(var):
    w = _World(broker_delay_s=0.3)
    s = _session(w)
    errors = []

    def go():
        try:
            s.get_quote("SPY")
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    ts = [threading.Thread(target=go) for _ in range(8)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert not errors and w.broker_calls == 1 and w.schwab_calls == 8


def test_schwab_401_refetches_once_then_surfaces(var):
    w = _World(schwab_401_first=True)
    s = _session(w)
    r = s.get_quote("SPY")
    assert r.status_code == 200 and w.broker_calls == 2 and w.schwab_calls == 2
    assert w.auth_headers[0] != w.auth_headers[1]


@pytest.mark.parametrize("status,needle", [(404, "disabled"), (503, "kind=auth"), (429, "42"), (500, "HTTP 500")])
def test_broker_errors_map_to_messages_without_secrets(var, status, needle):
    s = _session(_World(broker_status=status))
    with pytest.raises(BrokerError) as ei:
        s.get_quote("SPY")
    assert needle in str(ei.value) and SECRET not in str(ei.value)


def test_wrong_secret_is_reported_not_leaked(var):
    s = _BrokerSession(BROKER, "w" * 40, Path("nr7_bot"), transport=httpx.MockTransport(_World().handler))
    with pytest.raises(BrokerError) as ei:
        s.get_quote("SPY")
    assert "rejected" in str(ei.value) and "w" * 40 not in str(ei.value)


def test_sidecar_written_without_secret_and_no_token_file(var):
    w = _World()
    _session(w).get_quote("SPY")
    side = var / "schwab_token.json.issued"
    assert side.exists() and not (var / "schwab_token.json").exists()
    data = json.loads(side.read_text())
    assert set(data) == {"creation_timestamp"} and abs(data["creation_timestamp"] - int(w.issued.timestamp())) <= 1
    assert "ACCESS" not in side.read_text()
    assert schwab_feed.issued_at_utc() is not None


def test_from_broker_validates_config(monkeypatch, var):
    monkeypatch.delenv("CC_TOKEN_BROKER_URL", raising=False); monkeypatch.delenv("CC_TOKEN_BROKER_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="CC_TOKEN_BROKER_URL, CC_TOKEN_BROKER_SECRET"):
        SchwabFeed.from_broker(var)
    monkeypatch.setenv("CC_TOKEN_BROKER_URL", "http://insecure"); monkeypatch.setenv("CC_TOKEN_BROKER_SECRET", SECRET)
    with pytest.raises(RuntimeError, match="https"):
        SchwabFeed.from_broker(var)
    monkeypatch.setenv("CC_TOKEN_BROKER_URL", BROKER); monkeypatch.setenv("CC_TOKEN_BROKER_SECRET", "short")
    with pytest.raises(RuntimeError, match="under 32"):
        SchwabFeed.from_broker(var)
    monkeypatch.setenv("CC_TOKEN_BROKER_SECRET", SECRET)
    w = _World()
    feed = SchwabFeed.from_broker(var, transport=httpx.MockTransport(w.handler))
    out = feed.check("SPY")
    assert out["last"] == 100.5 and out["broker_url"] == BROKER and out["broker_fetches"] == 1
    assert SECRET not in json.dumps(out)
