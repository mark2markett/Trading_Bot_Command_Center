"""Pre-trade risk engine. Runs inside the bot process. Fails closed. Risk-reducing orders bypass pause/kill only."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from .control import Control
from .ledger import Ledger
from .manifest import PORTFOLIO_DEFAULTS, BotManifest

ET = ZoneInfo("America/New_York")


@dataclass
class Order:
    side: str                 # BUY | SELL | SELL_SHORT | BUY_TO_COVER
    qty: int
    type: str                 # MOC | MKT | LMT | STOP
    symbol: str
    ref_price: float          # last quote used for sizing / collar
    quote_age_s: float = 0.0
    reduces_risk: bool = False
    limit_price: float | None = None
    stop_price: float | None = None


@dataclass
class RiskResult:
    ok: bool
    checks: list[dict[str, Any]] = field(default_factory=list)
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "reason": self.reason, "checks": self.checks}


class Risk:
    def __init__(self, manifest: BotManifest, ledger: Ledger, control: Control):
        self.m = manifest
        self.L = ledger
        self.C = control

    def _lim(self, key: str) -> Any:
        return self.L.limit(self.m.id, key, self.m.limits.get(key))

    def _plim(self, key: str) -> Any:
        return self.L.limit("portfolio", key, PORTFOLIO_DEFAULTS[key])

    def pre_trade(self, o: Order) -> RiskResult:
        checks: list[dict[str, Any]] = []

        def fail(name: str, detail: str) -> RiskResult:
            checks.append({"check": name, "ok": False, "detail": detail})
            r = RiskResult(False, checks, f"{name}: {detail}")
            self._record(o, r)
            return r

        def passed(name: str, detail: str = "") -> None:
            checks.append({"check": name, "ok": True, "detail": detail})

        # 1. kill (fleet or bot). Fail closed if the control dir is missing.
        if not self.C.dir_ok():
            if not o.reduces_risk:
                return fail("control_dir", "control directory missing; treating as KILLED")
            passed("control_dir", "missing, but order reduces risk")
        elif self.C.killed():
            if not o.reduces_risk:
                return fail("kill", "fleet or bot is killed")
            passed("kill", "killed, but order reduces risk")
        else:
            passed("kill")

        # 2. pause (new entries only)
        if self.C.entries_paused() and not o.reduces_risk:
            return fail("pause", "new entries are paused")
        passed("pause")

        if o.reduces_risk:
            # Risk-reducing orders still get sanity checks but never size/count limits that would trap a position.
            if o.quote_age_s > float(self._lim("stale_quote_s")):
                passed("stale_quote", f"quote {o.quote_age_s:.0f}s old; allowed because order reduces risk")
            r = RiskResult(True, checks, "ok (risk-reducing)")
            self._record(o, r)
            return r

        # 3. size, position, exposure
        notional = abs(o.qty) * o.ref_price
        if o.qty <= 0:
            return fail("qty", "quantity must be positive")
        if o.qty > int(self._lim("max_order_qty")):
            return fail("max_order_qty", f"{o.qty} > {self._lim('max_order_qty')}")
        if notional > float(self._lim("max_order_usd")):
            return fail("max_order_usd", f"${notional:,.0f} > ${float(self._lim('max_order_usd')):,.0f}")
        if notional > float(self._lim("max_position_usd")):
            return fail("max_position_usd", f"${notional:,.0f} > ${float(self._lim('max_position_usd')):,.0f}")
        passed("size", f"${notional:,.0f}")
        eq = self.L.latest_broker_equity_total()
        if eq:
            gross = self.L.gross_exposure_usd() + notional
            cap = float(self._plim("max_gross_exposure"))
            if gross / eq > cap:
                return fail("max_gross_exposure", f"{gross/eq:.2f}x > {cap:.2f}x")
            passed("max_gross_exposure", f"{gross/eq:.2f}x")
        else:
            passed("max_gross_exposure", "no broker equity recorded yet; skipped")

        # 4. collar and staleness
        if o.quote_age_s > float(self._lim("stale_quote_s")):
            return fail("stale_quote", f"quote {o.quote_age_s:.0f}s old > {self._lim('stale_quote_s')}s")
        passed("stale_quote", f"{o.quote_age_s:.1f}s")
        px = o.limit_price or o.stop_price
        if px is not None and o.ref_price > 0:
            dev = abs(px / o.ref_price - 1)
            collar = float(self._lim("price_collar_pct"))
            if dev > collar and o.type != "STOP":
                return fail("price_collar", f"{dev:.2%} from quote > {collar:.2%}")
        passed("price_collar")

        # 5. orders per day, duplicates
        day = datetime.now(ET).date().isoformat()
        today = self.L.orders_today(self.m.id, day_prefix=datetime.now(timezone.utc).date().isoformat())
        if len(today) >= int(self._lim("max_orders_per_day")):
            return fail("max_orders_per_day", f"{len(today)} already today (limit {self._lim('max_orders_per_day')})")
        if any(r["side"] == o.side and (r["symbol"] or o.symbol) == o.symbol for r in today):
            return fail("duplicate", f"a {o.side} {o.symbol} was already sent today ({day})")
        passed("orders_per_day", f"{len(today)} so far")

        # 6. consecutive losses and bot drawdown -> auto-pause
        n = int(self._lim("max_consecutive_losses"))
        recent = self.L.recent_trades(self.m.id, n)
        if len(recent) >= n and all((r["pnl"] or 0) < 0 for r in recent):
            self.C.pause_bot(f"{n} consecutive losses", actor="sdk")
            self.L.alert("page" if self.m.mode == "live" else "digest", "auto_pause",
                         f"{self.m.name}: paused after {n} consecutive losses", self.m.id)
            return fail("consecutive_losses", f"{n} in a row; bot auto-paused")
        passed("consecutive_losses", f"{sum(1 for r in recent if (r['pnl'] or 0) < 0)} recent")
        pe = self.L.bot_peak_and_last_equity(self.m.id)
        if pe:
            peak, last = pe
            dd = 0.0 if peak <= 0 else (peak - last) / peak
            cap = float(self._lim("max_bot_dd"))
            if dd >= cap:
                self.C.pause_bot(f"bot drawdown {dd:.1%}", actor="sdk")
                self.L.alert("page" if self.m.mode == "live" else "digest", "auto_pause",
                             f"{self.m.name}: paused at drawdown {dd:.1%}", self.m.id)
                return fail("max_bot_dd", f"{dd:.1%} >= {cap:.0%}; bot auto-paused")
            passed("max_bot_dd", f"{dd:.1%}")

        r = RiskResult(True, checks, "ok")
        self._record(o, r)
        return r

    def _record(self, o: Order, r: RiskResult) -> None:
        """Rejected orders are written immediately (nothing was sent). Approved ones are written by run.order_sent()."""
        if not r.ok:
            self.L.order(self.m.id, side=o.side, qty=o.qty, type_=o.type, symbol=o.symbol, status="rejected",
                         reason=r.reason, risk_result=r.to_dict(), limit_price=o.limit_price, stop_price=o.stop_price,
                         ref_price=o.ref_price)
            self.L.alert("page" if self.m.mode == "live" else "digest", "order_rejected",
                         f"{self.m.name}: {o.side} {o.qty} {o.symbol} rejected — {r.reason}", self.m.id)
