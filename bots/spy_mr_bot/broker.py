"""
Broker layer. Two implementations behind one interface:

  SchwabBroker  - real Schwab Trader API via schwab-py (LIVE money; Schwab has no API paper account)
  PaperBroker   - simulates fills at the official daily close, keeps a ledger in paper_ledger.json

Both expose: daily_closes(symbol, n), last_price(symbol), position(symbol),
             buy_moc(symbol, qty), sell_moc(symbol, qty), place_stop(symbol, qty, stop),
             cancel_open_orders(symbol), equity()
"""
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional


class BrokerError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Schwab (live)
# ---------------------------------------------------------------------------
class SchwabBroker:
    def __init__(self, api_key: str, app_secret: str, callback_url: str, token_path: str,
                 account_index: int = 0):
        from schwab.auth import easy_client  # imported lazily so paper mode needs no schwab-py

        self.client = easy_client(api_key=api_key, app_secret=app_secret,
                                  callback_url=callback_url, token_path=token_path)
        accts = self._json(self.client.get_account_numbers())
        if not accts:
            raise BrokerError("No Schwab accounts visible to this token")
        self.account_hash = accts[account_index]["hashValue"]
        self.account_number = accts[account_index]["accountNumber"]

    @staticmethod
    def _json(resp):
        if resp.status_code >= 300:
            raise BrokerError(f"Schwab HTTP {resp.status_code}: {resp.text[:300]}")
        return resp.json() if resp.content else {}

    # ---- market data ----
    def daily_closes(self, symbol: str, n: int = 260) -> List[dict]:
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=int(n * 1.6) + 30)
        data = self._json(self.client.get_price_history_every_day(
            symbol, start_datetime=start, end_datetime=end, need_extended_hours_data=False))
        candles = data.get("candles", [])
        out = [{"date": datetime.fromtimestamp(c["datetime"] / 1000, tz=timezone.utc).date().isoformat(),
                "open": float(c["open"]), "high": float(c["high"]), "low": float(c["low"]),
                "close": float(c["close"])} for c in candles]
        return out[-n:]

    def last_price(self, symbol: str) -> float:
        q = self._json(self.client.get_quote(symbol))
        return float(q[symbol]["quote"]["lastPrice"])

    # ---- account ----
    def _account(self) -> dict:
        from schwab.client import Client
        return self._json(self.client.get_account(
            self.account_hash, fields=[Client.Account.Fields.POSITIONS]))["securitiesAccount"]

    def position(self, symbol: str) -> int:
        for p in self._account().get("positions", []):
            if p["instrument"].get("symbol") == symbol:
                return int(p.get("longQuantity", 0) - p.get("shortQuantity", 0))
        return 0

    def equity(self) -> float:
        bal = self._account()["currentBalances"]
        return float(bal.get("liquidationValue") or bal.get("equity"))

    # ---- orders ----
    def _place(self, order):
        resp = self.client.place_order(self.account_hash, order)
        if resp.status_code >= 300:
            raise BrokerError(f"Order rejected HTTP {resp.status_code}: {resp.text[:300]}")
        loc = resp.headers.get("location", "")
        return loc.rsplit("/", 1)[-1] if loc else "unknown"

    def buy_moc(self, symbol: str, qty: int) -> str:
        from schwab.orders.common import OrderType
        from schwab.orders.equities import equity_buy_market
        return self._place(equity_buy_market(symbol, qty).set_order_type(OrderType.MARKET_ON_CLOSE))

    def sell_moc(self, symbol: str, qty: int) -> str:
        from schwab.orders.common import OrderType
        from schwab.orders.equities import equity_sell_market
        return self._place(equity_sell_market(symbol, qty).set_order_type(OrderType.MARKET_ON_CLOSE))

    def place_stop(self, symbol: str, qty: int, stop: float) -> str:
        from schwab.orders.common import Duration, OrderType, Session
        from schwab.orders.equities import equity_sell_market
        order = (equity_sell_market(symbol, qty)
                 .set_order_type(OrderType.STOP)
                 .set_stop_price(f"{stop:.2f}")
                 .set_duration(Duration.GOOD_TILL_CANCEL)
                 .set_session(Session.NORMAL))
        return self._place(order)

    def cancel_open_orders(self, symbol: str) -> int:
        from schwab.client import Client
        now = datetime.now(timezone.utc)
        orders = self._json(self.client.get_orders_for_account(
            self.account_hash, from_entered_datetime=now - timedelta(days=60), to_entered_datetime=now,
            status=Client.Order.Status.WORKING))
        n = 0
        for o in orders:
            legs = o.get("orderLegCollection", [])
            if any(l["instrument"].get("symbol") == symbol for l in legs):
                self.client.cancel_order(o["orderId"], self.account_hash)
                n += 1
        return n


# ---------------------------------------------------------------------------
# Paper (simulated fills at the official close, real market data)
# ---------------------------------------------------------------------------
class PaperBroker:
    """
    Uses a data source for prices (Schwab if credentials exist, else Stooq CSV)
    and simulates fills at the official daily close. No order ever leaves this machine.
    """

    def __init__(self, ledger_path: str, starting_cash: float = 100_000.0, data=None):
        self.path = Path(ledger_path)
        self.data = data  # object with daily_closes() and last_price(); None -> Stooq
        if self.path.exists():
            self.ledger = json.loads(self.path.read_text())
        else:
            self.ledger = {"cash": starting_cash, "positions": {}, "pending": [], "fills": [], "stops": {}}
            self._save()

    def _save(self):
        self.path.write_text(json.dumps(self.ledger, indent=2))

    # ---- market data ----
    def daily_closes(self, symbol: str, n: int = 260) -> List[dict]:
        if self.data:
            return self.data.daily_closes(symbol, n)
        return _stooq_daily(symbol)[-n:]

    def last_price(self, symbol: str) -> float:
        if self.data:
            return self.data.last_price(symbol)
        return _stooq_daily(symbol)[-1]["close"]  # best available without a live feed

    # ---- account ----
    def position(self, symbol: str) -> int:
        return int(self.ledger["positions"].get(symbol, 0))

    def equity(self) -> float:
        eq = self.ledger["cash"]
        for sym, q in self.ledger["positions"].items():
            if q:
                eq += q * self.last_price(sym)
        return eq

    # ---- orders (queued, settled by settle_pending() using the real close) ----
    def _queue(self, kind: str, symbol: str, qty: int, **kw) -> str:
        oid = f"paper-{int(time.time()*1000)}"
        self.ledger["pending"].append({"id": oid, "kind": kind, "symbol": symbol, "qty": qty,
                                       "queued": datetime.now(timezone.utc).isoformat(), **kw})
        self._save()
        return oid

    def buy_moc(self, symbol, qty):  return self._queue("BUY_MOC", symbol, qty)
    def sell_moc(self, symbol, qty): return self._queue("SELL_MOC", symbol, qty)

    def place_stop(self, symbol, qty, stop):
        self.ledger["stops"][symbol] = {"qty": qty, "stop": stop}
        self._save()
        return f"paper-stop-{symbol}"

    def cancel_open_orders(self, symbol):
        n = 1 if symbol in self.ledger["stops"] else 0
        self.ledger["stops"].pop(symbol, None)
        self.ledger["pending"] = [p for p in self.ledger["pending"] if p["symbol"] != symbol]
        self._save()
        return n

    def settle_pending(self, bar: dict, slippage: float = 0.01, commission: float = 0.0035) -> List[dict]:
        """Fill queued MOC orders at bar['close'] and check stops against bar['low']. Returns fills."""
        fills = []
        for p in list(self.ledger["pending"]):
            px = bar["close"] + (slippage if p["kind"] == "BUY_MOC" else -slippage)
            sign = 1 if p["kind"] == "BUY_MOC" else -1
            self.ledger["cash"] -= sign * px * p["qty"] + commission * p["qty"]
            self.ledger["positions"][p["symbol"]] = self.position(p["symbol"]) + sign * p["qty"]
            fills.append({**p, "fill": px, "date": bar["date"]})
            self.ledger["pending"].remove(p)
        for sym, st in list(self.ledger["stops"].items()):
            if bar.get("low") is not None and bar["low"] <= st["stop"] and self.position(sym) > 0:
                px = min(st["stop"], bar.get("open", st["stop"])) - slippage
                self.ledger["cash"] += px * st["qty"] - commission * st["qty"]
                self.ledger["positions"][sym] = self.position(sym) - st["qty"]
                fills.append({"kind": "STOP", "symbol": sym, "qty": st["qty"], "fill": px, "date": bar["date"]})
                self.ledger["stops"].pop(sym)
        self.ledger["fills"].extend(fills)
        self._save()
        return fills


_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}


def _http(url: str) -> str:
    import urllib.request
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode()


def _stooq_daily(symbol: str) -> List[dict]:
    """Free end-of-day data (no key). Only used by paper mode when Schwab creds are absent.
    Tries Stooq, then Yahoo Finance. Either one is enough."""
    errors = []
    try:
        import csv
        import io
        txt = _http(f"https://stooq.com/q/d/l/?s={symbol.lower()}.us&i=d")
        rows = list(csv.DictReader(io.StringIO(txt)))
        if rows and "Close" in rows[0]:
            return [{"date": r["Date"], "open": float(r["Open"]), "high": float(r["High"]),
                     "low": float(r["Low"]), "close": float(r["Close"])} for r in rows if r.get("Close")]
        errors.append("Stooq: empty/limit")
    except Exception as e:  # noqa: BLE001
        errors.append(f"Stooq: {e}")
    try:
        j = json.loads(_http(f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=2y&interval=1d"))
        res = j["chart"]["result"][0]
        ts = res["timestamp"]; q = res["indicators"]["quote"][0]
        out = []
        for i, t in enumerate(ts):
            if q["close"][i] is None:
                continue
            out.append({"date": datetime.fromtimestamp(t, tz=timezone.utc).date().isoformat(),
                        "open": float(q["open"][i]), "high": float(q["high"][i]),
                        "low": float(q["low"][i]), "close": float(q["close"][i])})
        if out:
            return out
        errors.append("Yahoo: empty")
    except Exception as e:  # noqa: BLE001
        errors.append(f"Yahoo: {e}")
    raise BrokerError("No free data source reachable: " + "; ".join(errors))
