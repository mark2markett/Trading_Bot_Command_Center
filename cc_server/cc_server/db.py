"""Server-side read helpers over the shared ledger. Reuses cc_sdk.Ledger; adds aggregate queries."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from cc_sdk.ledger import Ledger, now_iso  # noqa: F401

ET_OFFSET_FALLBACK = -4


def rows(rs) -> list[dict[str, Any]]:
    return [dict(r) for r in rs]


def bot_rows(L: Ledger) -> list[dict[str, Any]]:
    out = []
    for b in L.q("SELECT * FROM bots ORDER BY name"):
        d = dict(b)
        for k in ("cadence_json", "backtest_json", "limits_json"):
            d[k[:-5]] = json.loads(d.pop(k) or "{}")
        out.append(d)
    return out


def last_heartbeat(L: Ledger, bot_id: str) -> dict[str, Any] | None:
    r = L.one("SELECT * FROM heartbeats WHERE bot_id=? ORDER BY id DESC LIMIT 1", (bot_id,))
    return dict(r) if r else None


def position(L: Ledger, bot_id: str) -> dict[str, Any] | None:
    r = L.one("SELECT * FROM positions WHERE bot_id=?", (bot_id,))
    return dict(r) if r else None


def equity_series(L: Ledger, bot_id: str, days: int = 400) -> list[tuple[str, float]]:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    return [(r["at"], float(r["equity"])) for r in L.q(
        "SELECT at, equity FROM equity WHERE bot_id=? AND source='bot' AND at>=? ORDER BY at", (bot_id, since))]


def broker_equity_series(L: Ledger, days: int = 400) -> list[tuple[str, float]]:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    return [(r["at"], float(r["equity"])) for r in L.q(
        "SELECT at, equity FROM equity WHERE source='broker' AND at>=? ORDER BY at", (since,))]


def trades(L: Ledger, bot_id: str, limit: int = 200) -> list[dict[str, Any]]:
    return rows(L.q("SELECT * FROM trades WHERE bot_id=? ORDER BY exit_at DESC LIMIT ?", (bot_id, limit)))


def decisions(L: Ledger, bot_id: str, limit: int = 60) -> list[dict[str, Any]]:
    out = rows(L.q("SELECT * FROM decisions WHERE bot_id=? ORDER BY id DESC LIMIT ?", (bot_id, limit)))
    for d in out:
        d["signal"] = json.loads(d.pop("signal_json") or "{}")
    return out


def fills(L: Ledger, bot_id: str | None = None, limit: int = 30) -> list[dict[str, Any]]:
    if bot_id:
        return rows(L.q("""SELECT f.*, o.side, o.type, o.symbol, b.name bot_name FROM fills f
                           LEFT JOIN orders o ON o.id=f.order_id LEFT JOIN bots b ON b.id=f.bot_id
                           WHERE f.bot_id=? ORDER BY f.id DESC LIMIT ?""", (bot_id, limit)))
    return rows(L.q("""SELECT f.*, o.side, o.type, o.symbol, b.name bot_name FROM fills f
                       LEFT JOIN orders o ON o.id=f.order_id LEFT JOIN bots b ON b.id=f.bot_id
                       ORDER BY f.id DESC LIMIT ?""", (limit,)))


def open_orders(L: Ledger) -> list[dict[str, Any]]:
    return rows(L.q("""SELECT o.*, b.name bot_name FROM orders o LEFT JOIN bots b ON b.id=o.bot_id
                       WHERE o.status='sent' ORDER BY o.at DESC LIMIT 50"""))


def alerts(L: Ledger, limit: int = 50, unacked_only: bool = False) -> list[dict[str, Any]]:
    sql = "SELECT a.*, b.name bot_name FROM alerts a LEFT JOIN bots b ON b.id=a.bot_id"
    if unacked_only:
        sql += " WHERE a.acknowledged_at IS NULL"
    sql += " ORDER BY a.id DESC LIMIT ?"
    return rows(L.q(sql, (limit,)))


def controls(L: Ledger, limit: int = 50) -> list[dict[str, Any]]:
    out = rows(L.q("SELECT * FROM controls ORDER BY id DESC LIMIT ?", (limit,)))
    for c in out:
        c["before"] = json.loads(c.pop("before_json") or "null")
        c["after"] = json.loads(c.pop("after_json") or "null")
    return out


def limits(L: Ledger, scope: str) -> dict[str, Any]:
    return {r["key"]: json.loads(r["value_json"]) for r in L.q("SELECT key, value_json FROM limits WHERE scope=?", (scope,))}


def rejected_orders_24h(L: Ledger, bot_id: str) -> int:
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    r = L.one("SELECT COUNT(*) n FROM orders WHERE bot_id=? AND status='rejected' AND at>=?", (bot_id, since))
    return int(r["n"]) if r else 0


def kv_get(L: Ledger, key: str, default: Any = None) -> Any:
    r = L.one("SELECT value_json FROM kv WHERE key=?", (key,))
    return json.loads(r["value_json"]) if r else default


def kv_set(L: Ledger, key: str, value: Any) -> None:
    L.x("INSERT INTO kv(key,value_json,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at",
        (key, json.dumps(value, default=str), now_iso()))
