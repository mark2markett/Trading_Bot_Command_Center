"""cc_sdk — what every bot imports. Heartbeats, decisions, orders, fills, positions, equity, and fail-closed risk checks."""
from __future__ import annotations

import json
import logging
import os
import traceback
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .control import Control
from .ledger import Ledger, now_iso
from .manifest import BotManifest
from .risk import Order, Risk, RiskResult

__all__ = ["Bot", "BotManifest", "Order", "RiskResult", "Run", "Ledger", "Control"]


class Run:
    """One scheduled command execution. Created by Bot.run()."""

    def __init__(self, bot: Bot, name: str):
        self.bot = bot
        self.name = name
        self.L = bot.L

    def decision(self, signal: dict[str, Any], action: str, reason: str) -> int:
        return self.L.decision(self.bot.m.id, self.name, signal, action, reason)

    def order_sent(self, o: Order, result: RiskResult, broker_order_id: str | None, reason: str = "") -> int:
        return self.L.order(self.bot.m.id, side=o.side, qty=o.qty, type_=o.type, symbol=o.symbol, status="sent",
                            reason=reason, risk_result=result.to_dict(), broker_order_id=broker_order_id,
                            limit_price=o.limit_price, stop_price=o.stop_price, ref_price=o.ref_price)

    def order_rejected(self, o: Order, result: RiskResult) -> None:
        # Already recorded by Risk._record(); kept for readability at call sites.
        return None

    def note(self, message: str, severity: str = "info", kind: str = "note") -> int:
        return self.L.alert(severity, kind, f"{self.bot.m.name}: {message}", self.bot.m.id)


class Bot:
    def __init__(self, manifest: BotManifest, db_path: Path | None = None, control_dir: Path | None = None):
        self.m = manifest
        self.L = Ledger(db_path)
        self.control = Control(manifest.id, control_dir)
        self.risk = Risk(manifest, self.L, self.control)
        self.L.upsert_bot(manifest.to_row())
        self.L.set_bot_status(manifest.id, self.control.status_word())
        self._diagnostic_error_reported = False

    def event(self, event: str, **fields: Any) -> None:
        """Durable process diagnostics without a file handle that blocks Windows cleanup."""
        try:
            directory = self.L.path.parent / "logs"
            directory.mkdir(parents=True, exist_ok=True)
            row = {"at": now_iso(), "bot_id": self.m.id, "pid": os.getpid(), "event": event, **fields}
            with (directory / f"{self.m.id}.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(row) + "\n")
        except (OSError, TypeError, ValueError) as error:
            # Optional diagnostics must never interrupt exits or mask the ledger's original failure.
            if not self._diagnostic_error_reported:
                self._diagnostic_error_reported = True
                try:
                    logging.getLogger(__name__).warning("diagnostic log unavailable for %s (%s)", self.m.id, type(error).__name__)
                except Exception:  # noqa: BLE001 — only the fallback diagnostic handler
                    pass

    @contextmanager
    def run(self, name: str) -> Iterator[Run]:
        r = Run(self, name)
        self.event("run_started", run=name, mode=self.m.mode, version=self.m.version)
        try:
            yield r
        except Exception as e:  # noqa: BLE001
            self.event("run_failed", run=name, error_type=type(e).__name__)
            self.L.heartbeat(self.m.id, name, ok=False, detail=f"{e}\n{traceback.format_exc()}")
            self.L.alert("page" if self.m.mode == "live" else "digest", "run_failed",
                         f"{self.m.name}: {name} failed — {e}", self.m.id)
            raise
        else:
            self.L.heartbeat(self.m.id, name, ok=True)
            self.event("run_completed", run=name)
        finally:
            self.L.set_bot_status(self.m.id, self.control.status_word())

    # ---- convenience writes ----
    def record_fill(self, order_id: int | None, qty: int, price: float, expected_price: float, commission: float = 0.0) -> int:
        fid = self.L.fill(self.m.id, order_id, qty, price, expected_price, commission)
        if order_id:
            self.L.x("UPDATE orders SET status='filled' WHERE id=?", (order_id,))
        return fid

    def set_position(self, symbol: str, qty: int, avg_price: float | None = None, entry_at: str | None = None,
                     bars_held: int = 0, stop_price: float | None = None, side: str | None = None) -> None:
        self.L.set_position(self.m.id, symbol, qty, avg_price, entry_at, bars_held, stop_price, side)

    def positions(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self.L.positions_for(self.m.id)]

    def record_equity(self, value: float, source: str = "bot") -> int:
        return self.L.equity(self.m.id, value, source)

    def record_trade(self, **kw: Any) -> int:
        return self.L.trade(self.m.id, **kw)

    def last_sent_order_id(self, side: str) -> int | None:
        r = self.L.one("SELECT id FROM orders WHERE bot_id=? AND side=? AND status='sent' ORDER BY at DESC LIMIT 1",
                       (self.m.id, side))
        return int(r["id"]) if r else None

    @property
    def now(self) -> str:
        return now_iso()
