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
        assert callable(getattr(SchwabFeed, name, None)), (
            f"SchwabFeed.{name} missing — a module-level def slipped into the class body"
        )
    assert callable(schwab_feed.write_issued_sidecar)
    assert not hasattr(SchwabFeed, "write_issued_sidecar")
    assert not hasattr(SchwabFeed, "from_env") and not hasattr(SchwabFeed, "from_refresh_token")


def test_broker_session_has_no_trading_surface():
    """Paper-only guarantee on the fleet side: no accounts / orders / transactions method exists to call."""
    names = {n for n in dir(_BrokerSession) if not n.startswith("__")}
    for banned in (
        "place_order",
        "cancel_order",
        "get_account",
        "get_accounts",
        "get_orders",
        "get_transactions",
        "replace_order",
        "preview_order",
    ):
        assert banned not in names
    # Exactly four read-only market-data calls (M7.1 added the option chain). Anything else is a new surface.
    assert {n for n in names if n.startswith("get_")} == {
        "get_quote",
        "get_price_history_every_minute",
        "get_price_history_every_day",
        "get_option_chain",
    }


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
        return _Resp({symbol: {"quote": {"lastPrice": 567.89, "quoteTime": time.time() * 1000}}})

    def get_price_history_every_minute(self, symbol, start_datetime, end_datetime, need_extended_hours_data):
        base = start_datetime.replace(hour=9, minute=30, second=0, microsecond=0)
        candles = [
            {
                "datetime": int(base.replace(minute=30 + i).timestamp() * 1000),
                "open": 1,
                "high": 2,
                "low": 0.5,
                "close": 1.5,
                "volume": 100,
            }
            for i in range(2)
        ]
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
            return httpx.Response(
                200,
                json={
                    "access_token": f"ACCESS-{self.n}-{'x' * 30}",
                    "token_type": "Bearer",
                    "expires_at": exp,
                    "scope": "market-data-only",
                    "refresh_issued_at": self.issued.isoformat().replace("+00:00", "Z"),
                    "refresh_days_left": 6.0,
                },
            )
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
    r1 = s.get_quote("SPY")
    r2 = s.get_quote("QQQ")
    assert r1.status_code == 200 and r2.json()["QQQ"]["quote"]["lastPrice"] == 100.5
    assert w.broker_calls == 1 and w.schwab_calls == 2
    assert w.auth_headers == [f"Bearer ACCESS-1-{'x' * 30}"] * 2
    assert w.bot_headers == ["gap_go_bot"]


def test_refreshes_before_expiry(var):
    w = _World(expires_in_s=schwab_feed.REFRESH_EARLY_S - 5)  # already inside the early-refresh window
    s = _session(w)
    s.get_quote("SPY")
    s.get_quote("SPY")
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
    [t.start() for t in ts]
    [t.join() for t in ts]
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
    monkeypatch.delenv("CC_TOKEN_BROKER_URL", raising=False)
    monkeypatch.delenv("CC_TOKEN_BROKER_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="CC_TOKEN_BROKER_URL, CC_TOKEN_BROKER_SECRET"):
        SchwabFeed.from_broker(var)
    monkeypatch.setenv("CC_TOKEN_BROKER_URL", "http://insecure")
    monkeypatch.setenv("CC_TOKEN_BROKER_SECRET", SECRET)
    with pytest.raises(RuntimeError, match="https"):
        SchwabFeed.from_broker(var)
    monkeypatch.setenv("CC_TOKEN_BROKER_URL", BROKER)
    monkeypatch.setenv("CC_TOKEN_BROKER_SECRET", "short")
    with pytest.raises(RuntimeError, match="under 32"):
        SchwabFeed.from_broker(var)
    monkeypatch.setenv("CC_TOKEN_BROKER_SECRET", SECRET)
    w = _World()
    feed = SchwabFeed.from_broker(var, transport=httpx.MockTransport(w.handler))
    out = feed.check("SPY")
    assert out["last"] == 100.5 and out["broker_url"] == BROKER and out["broker_fetches"] == 1
    assert SECRET not in json.dumps(out)


# ---- shared token state (M6.9): same pattern as M2M's other apps ----
from cc_sdk.schwab_feed import _SharedStateSession  # noqa: E402

SB = "https://sb.test"
SERVICE = "k" * 40
REFRESH = "r" * 140


class _SharedWorld:
    def __init__(self, *, rotate=False, token_status=200):
        self.rotate, self.token_status = rotate, token_status
        self.patches, self.token_posts, self.reads = [], 0, 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "sb.test":
            assert request.headers.get("apikey") == SERVICE
            if request.method == "GET":
                self.reads += 1
                return httpx.Response(
                    200, json=[{"schwab_token_state": {"refresh_token": REFRESH, "issued_at": "2026-10-04T02:26:41.289Z"}}]
                )
            self.patches.append(json.loads(request.content))
            return httpx.Response(204)
        if request.url.path == "/v1/oauth/token":
            self.token_posts += 1
            assert request.headers["authorization"].startswith("Basic ")
            if self.token_status != 200:
                return httpx.Response(self.token_status, json={"error": "invalid_grant", "error_description": REFRESH})
            body = {"access_token": "A" * 40, "expires_in": 1800, "token_type": "Bearer"}
            body["refresh_token"] = ("n" * 140) if self.rotate else REFRESH
            return httpx.Response(200, json=body)
        sym = request.url.path.split("/")[-2]
        return httpx.Response(200, json={sym: {"quote": {"lastPrice": 101.25, "quoteTime": int(time.time() * 1000)}}})


def _shared(w):
    return _SharedStateSession(SB, SERVICE, "c" * 32, "s" * 16, Path("gap_go_bot"), transport=httpx.MockTransport(w.handler))


def test_shared_state_reads_row_and_never_writes_without_rotation(var):
    w = _SharedWorld()
    s = _shared(w)
    assert s.get_quote("SPY").json()["SPY"]["quote"]["lastPrice"] == 101.25
    s.get_quote("QQQ")
    assert w.reads == 1 and w.token_posts == 1 and w.patches == []
    assert (var / "schwab_token.json.issued").exists() and not (var / "schwab_token.json").exists()


def test_shared_state_writes_back_only_on_rotation(var):
    w = _SharedWorld(rotate=True)
    _shared(w).get_quote("SPY")
    assert len(w.patches) == 1
    st = w.patches[0]["schwab_token_state"]
    assert st["refresh_token"] == "n" * 140 and st["issued_at"] == st["last_refreshed_at"]


def test_shared_state_refusal_never_leaks(var):
    s = _shared(_SharedWorld(token_status=400))
    with pytest.raises(BrokerError) as ei:
        s.get_quote("SPY")
    msg = str(ei.value)
    assert "HTTP 400, invalid_grant" in msg and REFRESH not in msg and SERVICE not in msg


def test_connect_prefers_shared_state_when_configured(monkeypatch, var):
    for k, v in {
        "SCHWAB_CLIENT_ID": "c" * 32,
        "SCHWAB_CLIENT_SECRET": "s" * 16,
        "SUPABASE_URL": SB,
        "SUPABASE_SERVICE_ROLE_KEY": SERVICE,
    }.items():
        monkeypatch.setenv(k, v)
    w = _SharedWorld()
    out = SchwabFeed.connect(var, transport=httpx.MockTransport(w.handler)).check("SPY")
    assert out["last"] == 101.25 and out["broker_url"] == "shared-state"
    assert SERVICE not in json.dumps(out)


def test_minute_history_cache_covers_polls_but_refreshes_at_minute_boundary(monkeypatch):
    clock = [datetime(2026, 10, 6, 10, 0, 1, tzinfo=ET).timestamp()]
    monkeypatch.setattr(schwab_feed.time, "time", lambda: clock[0])

    class Counting(_FakeClient):
        calls = 0

        def get_price_history_every_minute(self, *args, **kwargs):
            self.calls += 1
            return super().get_price_history_every_minute(*args, **kwargs)

    client = Counting()
    feed = SchwabFeed(client)
    day = datetime.fromtimestamp(clock[0], ET)
    feed.minute_bars("SPY", day)
    for elapsed in (15, 30, 45):
        clock[0] = day.timestamp() + elapsed
        feed.minute_bars("SPY", day)
    assert client.calls == 1
    clock[0] = day.timestamp() + 60
    feed.minute_bars("SPY", day)
    assert client.calls == 2


def test_history_429_cooldown_honors_retry_after_without_blocking_quotes(monkeypatch, tmp_path):
    clock = [1000000.0]
    monkeypatch.setattr(schwab_feed.time, "time", lambda: clock[0])
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.url.path.endswith("pricehistory"):
            return httpx.Response(429, headers={"Retry-After": "60"})
        return httpx.Response(200, json={"SPY": {"quote": {"lastPrice": 500, "quoteTime": clock[0] * 1000}}})

    session = _BrokerSession(BROKER, SECRET, tmp_path, transport=httpx.MockTransport(handler))
    session._access = "a" * 40
    session._expires_at = clock[0] + 1800
    day = datetime(2026, 10, 6, tzinfo=ET)
    feed = SchwabFeed(session)
    with pytest.raises(httpx.HTTPStatusError):
        feed.minute_bars("SPY", day)
    clock[0] += 15
    with pytest.raises(httpx.HTTPStatusError):
        feed.minute_bars("SPY", day)
    assert calls.count("/marketdata/v1/pricehistory") == 1
    assert feed.quote("SPY") == (500, 0)
    clock[0] += 45
    with pytest.raises(httpx.HTTPStatusError):
        feed.minute_bars("SPY", day)
    assert calls.count("/marketdata/v1/pricehistory") == 2


@pytest.mark.parametrize("timestamp", [None, float("nan"), float("inf"), (time.time() + 3600) * 1000])
def test_missing_invalid_and_future_quote_times_are_refused(timestamp):
    class Client:
        def get_quote(self, symbol):
            quote = {"lastPrice": 500}
            if timestamp is not None:
                quote["quoteTime"] = timestamp
            return _Resp({symbol: {"quote": quote}})

    with pytest.raises(ValueError):
        SchwabFeed(Client()).quote("SPY")


def test_option_account_mark_uses_current_book_instead_of_old_last_trade():
    symbol = "SPY   261009C00500000"

    class Client:
        def get_quote(self, symbol):
            return _Resp({symbol: {"quote": {"lastPrice": 5, "bidPrice": 0.9, "askPrice": 1.1, "quoteTime": time.time() * 1000}}})

    price, age = SchwabFeed(Client()).account_quote(symbol)
    assert price == 1 and age < 1


def test_connect_reads_bot_local_broker_configuration(monkeypatch, tmp_path):
    botdir = tmp_path / "spy_mr_bot"
    botdir.mkdir()
    (botdir / ".env.local").write_text("CC_TOKEN_BROKER_URL=" + BROKER + "\nCC_TOKEN_BROKER_SECRET=" + SECRET + "\n")
    monkeypatch.setattr(schwab_feed, "REPO_ROOT", tmp_path)
    for key in (*schwab_feed.SHARED_VARS, "CC_TOKEN_BROKER_URL", "CC_TOKEN_BROKER_SECRET"):
        monkeypatch.delenv(key, raising=False)
    feed = SchwabFeed.connect(botdir, transport=httpx.MockTransport(lambda request: httpx.Response(200)))
    assert isinstance(feed.c, _BrokerSession)
