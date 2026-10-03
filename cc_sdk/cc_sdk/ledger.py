"""SQLite ledger shared by bots and the server. Small typed helpers over sqlite3; no ORM."""
from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = Path(__file__).with_name("schema.sql").read_text()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def var_dir() -> Path:
    """Runtime directory. CC_VAR env var wins; else <repo>/var resolved from this file; else ./var."""
    env = os.getenv("CC_VAR")
    if env:
        return Path(env)
    here = Path(__file__).resolve()
    for p in here.parents:
        if (p / "pyproject.toml").exists() and (p / "cc_sdk").exists():
            return p / "var"
    return Path.cwd() / "var"


def db_path() -> Path:
    return var_dir() / "cc.db"


class Ledger:
    def __init__(self, path: Path | None = None):
        self.path = path or db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, timeout=10, isolation_level=None, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    # ---- generic ----
    def q(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        return self.conn.execute(sql, tuple(params)).fetchall()

    def one(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
        return self.conn.execute(sql, tuple(params)).fetchone()

    def x(self, sql: str, params: Iterable[Any] = ()) -> int:
        cur = self.conn.execute(sql, tuple(params))
        return int(cur.lastrowid or 0)

    # ---- bots ----
    def upsert_bot(self, m: dict[str, Any]) -> None:
        self.x(
            """INSERT INTO bots(id,name,strategy_line,mode,version,instrument,cadence_json,backtest_json,limits_json,status,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,'running',?,?)
               ON CONFLICT(id) DO UPDATE SET name=excluded.name, strategy_line=excluded.strategy_line, mode=excluded.mode,
                 version=excluded.version, instrument=excluded.instrument, cadence_json=excluded.cadence_json,
                 backtest_json=excluded.backtest_json, limits_json=excluded.limits_json, updated_at=excluded.updated_at""",
            (m["id"], m["name"], m["strategy_line"], m["mode"], m["version"], m["instrument"],
             json.dumps(m["cadence"]), json.dumps(m["backtest"]), json.dumps(m["limits"]), now_iso(), now_iso()),
        )

    def set_bot_status(self, bot_id: str, status: str) -> None:
        self.x("UPDATE bots SET status=?, updated_at=? WHERE id=?", (status, now_iso(), bot_id))

    # ---- writes from bots ----
    def heartbeat(self, bot_id: str, run: str, ok: bool, detail: str = "") -> int:
        return self.x("INSERT INTO heartbeats(bot_id,run,at,ok,detail) VALUES(?,?,?,?,?)",
                      (bot_id, run, now_iso(), int(ok), detail[:4000]))

    def decision(self, bot_id: str, run: str, signal: dict[str, Any], action: str, reason: str) -> int:
        return self.x("INSERT INTO decisions(bot_id,at,run,signal_json,action,reason) VALUES(?,?,?,?,?,?)",
                      (bot_id, now_iso(), run, json.dumps(signal, default=str), action, reason))

    def order(self, bot_id: str, *, side: str, qty: int, type_: str, symbol: str, status: str, reason: str,
              risk_result: dict[str, Any], broker_order_id: str | None = None, limit_price: float | None = None,
              stop_price: float | None = None, ref_price: float | None = None) -> int:
        return self.x(
            """INSERT INTO orders(bot_id,at,broker_order_id,side,qty,type,limit_price,stop_price,status,reason,risk_result_json,symbol,ref_price)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (bot_id, now_iso(), broker_order_id, side, qty, type_, limit_price, stop_price, status, reason,
             json.dumps(risk_result, default=str), symbol, ref_price))

    def fill(self, bot_id: str, order_id: int | None, qty: int, price: float, expected_price: float,
             commission: float = 0.0) -> int:
        slip = round(price - expected_price, 4)
        return self.x("INSERT INTO fills(order_id,bot_id,at,qty,price,expected_price,slippage,commission) VALUES(?,?,?,?,?,?,?,?)",
                      (order_id, bot_id, now_iso(), qty, price, expected_price, slip, commission))

    def set_position(self, bot_id: str, symbol: str, qty: int, avg_price: float | None, entry_at: str | None,
                     bars_held: int) -> None:
        self.x("""INSERT INTO positions(bot_id,symbol,qty,avg_price,entry_at,bars_held,updated_at) VALUES(?,?,?,?,?,?,?)
                  ON CONFLICT(bot_id) DO UPDATE SET symbol=excluded.symbol, qty=excluded.qty, avg_price=excluded.avg_price,
                  entry_at=excluded.entry_at, bars_held=excluded.bars_held, updated_at=excluded.updated_at""",
               (bot_id, symbol, qty, avg_price, entry_at, bars_held, now_iso()))

    def equity(self, bot_id: str, value: float, source: str = "bot") -> int:
        return self.x("INSERT INTO equity(bot_id,at,equity,source) VALUES(?,?,?,?)", (bot_id, now_iso(), value, source))

    def trade(self, bot_id: str, *, entry_at: str, exit_at: str, qty: int, entry_px: float, exit_px: float,
              bars: int, exit_reason: str, pnl: float, slippage: float) -> int:
        return self.x("""INSERT INTO trades(bot_id,entry_at,exit_at,qty,entry_px,exit_px,bars,exit_reason,pnl,slippage)
                         VALUES(?,?,?,?,?,?,?,?,?,?)""",
                      (bot_id, entry_at, exit_at, qty, entry_px, exit_px, bars, exit_reason, pnl, slippage))

    def alert(self, severity: str, kind: str, message: str, bot_id: str | None = None) -> int:
        return self.x("INSERT INTO alerts(at,severity,bot_id,kind,message) VALUES(?,?,?,?,?)",
                      (now_iso(), severity, bot_id, kind, message))

    def control(self, actor: str, action: str, target: str, before: Any, after: Any, note: str = "") -> int:
        return self.x("INSERT INTO controls(at,actor,action,target,before_json,after_json,note) VALUES(?,?,?,?,?,?,?)",
                      (now_iso(), actor, action, target, json.dumps(before, default=str), json.dumps(after, default=str), note))

    # ---- reads used by risk ----
    def limit(self, scope: str, key: str, default: Any) -> Any:
        r = self.one("SELECT value_json FROM limits WHERE scope=? AND key=?", (scope, key))
        return json.loads(r["value_json"]) if r else default

    def set_limit(self, scope: str, key: str, value: Any) -> None:
        self.x("""INSERT INTO limits(scope,key,value_json,updated_at) VALUES(?,?,?,?)
                  ON CONFLICT(scope,key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at""",
               (scope, key, json.dumps(value), now_iso()))

    def latest_broker_equity_total(self) -> float | None:
        rows = self.q("""SELECT e.bot_id, e.equity FROM equity e
                         JOIN (SELECT bot_id, MAX(at) at FROM equity WHERE source='broker' GROUP BY bot_id) m
                           ON m.bot_id=e.bot_id AND m.at=e.at WHERE e.source='broker'""")
        if not rows:
            return None
        # Bots share one account; broker equity is account-level. Use the most recent single value.
        r = self.one("SELECT equity FROM equity WHERE source='broker' ORDER BY at DESC LIMIT 1")
        return float(r["equity"]) if r else None

    def gross_exposure_usd(self) -> float:
        rows = self.q("SELECT qty, avg_price FROM positions WHERE qty != 0")
        return float(sum(abs(r["qty"]) * (r["avg_price"] or 0.0) for r in rows))

    def orders_today(self, bot_id: str, day_prefix: str) -> list[sqlite3.Row]:
        return self.q("SELECT side, status FROM orders WHERE bot_id=? AND at LIKE ? AND status IN ('sent','filled')",
                      (bot_id, day_prefix + "%"))

    def recent_trades(self, bot_id: str, n: int) -> list[sqlite3.Row]:
        return self.q("SELECT pnl FROM trades WHERE bot_id=? ORDER BY exit_at DESC LIMIT ?", (bot_id, n))

    def bot_peak_and_last_equity(self, bot_id: str) -> tuple[float, float] | None:
        rows = self.q("SELECT equity FROM equity WHERE bot_id=? ORDER BY at", (bot_id,))
        if not rows:
            return None
        vals = [float(r["equity"]) for r in rows]
        return max(vals), vals[-1]
