"""Options session runner (M7.4 + M7.5, docs/06_OPTIONS_M7_SPEC.md): an intraday signal expressed as a same-day debit
vertical, paper only.

Reuses `SessionRunner` for everything that is not option-specific — the poll loop, controls (kill / pause / flatten),
stops and end-of-day flatten are all judged on the UNDERLYING, exactly as the equity bot does. Only entry and exit
change: entry buys a debit spread through `Risk.pre_trade_spread`; exit closes both legs (risk-reducing, never
blocked). Every closed spread also records what shares holding the same delta would have made, so the report can say
whether the spread adds anything over the signal traded in shares (the M2M lesson: option P&L in isolation hides
leverage).
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Protocol

from . import Order
from .intraday import CLOSE_MIN, ET, Feed, OpenPos, SessionRunner, Signal
from .ledger import now_iso
from .options import CONTRACT_MULTIPLIER, OptionQuote, fill_spread, intrinsic, paper_fill_price, spread_pnl

LIVE_EVERY_S = 60.0       # refresh the dashboard's live Greeks at most once a minute per open spread


class ChainFeed(Feed, Protocol):
    def chain(self, symbol: str, from_date: date, to_date: date, strike_count: int | None = 40) -> list[OptionQuote]: ...


@dataclass
class OpenSpread(OpenPos):
    expiry: str = ""
    right: str = ""
    legs: list[str] = field(default_factory=list)            # [long OCC, short OCC]
    entry_prices: list[float] = field(default_factory=list)  # per share, as filled
    net_debit: float = 0.0
    und_entry: float = 0.0
    net_delta: float = 0.0                                   # per share at entry: long delta minus short delta


def pick_vertical(chain: list[OptionQuote], spot: float, side: int, atr: float, today: date, *,
                  dte_min: int, dte_max: int, width_atr: float) -> tuple[tuple[OptionQuote, OptionQuote] | None, str]:
    """Nearest expiry with dte_min..dte_max calendar days left. Long leg: strike nearest spot. Short leg: the listed
    strike nearest `width_atr` ATRs further in the signal direction (strictly beyond the long strike)."""
    right = "C" if side > 0 else "P"
    cands = [q for q in chain if q.right == right and dte_min <= (q.expiry - today).days <= dte_max]
    if not cands:
        return None, f"no {right} expiry {dte_min}-{dte_max} days out"
    expiry = min(q.expiry for q in cands)
    by_strike = {q.strike: q for q in cands if q.expiry == expiry}
    strikes = sorted(by_strike)
    long_k = min(strikes, key=lambda k: abs(k - spot))
    beyond = [k for k in strikes if (k > long_k if side > 0 else k < long_k)]
    if not beyond:
        return None, f"no strike beyond {long_k} for the short leg"
    target = long_k + side * width_atr * atr
    short_k = min(beyond, key=lambda k: abs(k - target))
    return (by_strike[long_k], by_strike[short_k]), ""


class SpreadSessionRunner(SessionRunner):
    def __init__(self, bot: Any, feed: ChainFeed, rules: Any, symbols: list[str], *, dte_min: int = 2, dte_max: int = 7,
                 width_atr: float = 1.0, **kw: Any):
        super().__init__(bot, feed, rules, symbols, **kw)
        self.cfeed = feed
        self.dte_min, self.dte_max, self.width_atr = dte_min, dte_max, width_atr
        self._live_at: dict[str, float] = {}

    # ---- crash recovery: open spreads are remembered in kv, not reconstructed from leg rows ----
    def _kv_key(self, underlying: str) -> str:
        return f"spread:{self.bot.m.id}:{underlying}"

    # ---- live Greeks for the dashboard (M7.4). The server never calls a vendor; it reads these kv rows. ----
    def _live_key(self, underlying: str) -> str:
        return f"optlive:{self.bot.m.id}:{underlying}"

    def _record_live(self, pos: OpenSpread, long_q: OptionQuote | None, short_q: OptionQuote | None, now: datetime) -> None:
        if long_q is None or short_q is None:
            return
        mult = CONTRACT_MULTIPLIER * pos.qty
        value = long_q.mid - short_q.mid
        rec = {"underlying": pos.symbol, "right": pos.right, "expiry": pos.expiry, "qty": pos.qty,
               "legs": [o.strip() for o in pos.legs], "strikes": [long_q.strike, short_q.strike],
               "dte": (date.fromisoformat(pos.expiry) - now.date()).days,
               "delta_shares": round(((long_q.delta or 0.0) - (short_q.delta or 0.0)) * mult, 1),
               "theta_usd_day": round(((long_q.theta or 0.0) - (short_q.theta or 0.0)) * mult, 2),
               "value_usd": round(value * mult, 2), "cost_usd": round(pos.net_debit * mult, 2),
               "unrealized_usd": round((value - pos.net_debit) * mult, 2), "updated_at": now_iso()}
        self.bot.L.x("INSERT INTO kv(key,value_json,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET "
                     "value_json=excluded.value_json, updated_at=excluded.updated_at",
                     (self._live_key(pos.symbol), json.dumps(rec), now_iso()))
        self._live_at[pos.symbol] = now.timestamp()

    def _refresh_live(self, now: datetime) -> None:
        for s, pos in list(self.open.items()):
            if not isinstance(pos, OpenSpread) or now.timestamp() - self._live_at.get(s, 0.0) < LIVE_EVERY_S:
                continue
            try:
                exp = date.fromisoformat(pos.expiry)
                by_occ = {q.occ: q for q in self.cfeed.chain(s, exp, exp)}
                self._record_live(pos, by_occ.get(pos.legs[0]), by_occ.get(pos.legs[1]), now)
            except Exception:  # noqa: BLE001 — display data only; never let it disturb the session
                self._live_at[s] = now.timestamp()

    def step(self, now: datetime) -> None:
        super().step(now)
        self._refresh_live(now)

    def prepare(self, day: datetime) -> None:
        adopt, self.adopt_positions = self.adopt_positions, False     # the equity adopter would misread OCC legs
        try:
            super().prepare(day)
        finally:
            self.adopt_positions = adopt
        if not adopt:
            return
        for row in self.bot.L.q("SELECT key, value_json FROM kv WHERE key LIKE ?", (f"spread:{self.bot.m.id}:%",)):
            pos = OpenSpread(**json.loads(row["value_json"]))
            self.open[pos.symbol] = pos
            self.traded_today.add(pos.symbol)
            self.bot.L.decision(self.bot.m.id, "session", {"symbol": pos.symbol, "legs": pos.legs}, "ADOPT",
                                "open spread left by an earlier session")

    def _now(self) -> datetime:
        clock = getattr(self.cfeed, "clock", None)   # replay feeds pretend a time; live uses the wall clock
        return clock if clock is not None else datetime.now(ET)

    def _none(self, s: str, sig: Signal, why: str) -> None:
        self.bot.L.decision(self.bot.m.id, "session", {"symbol": s, "signal": sig.reason}, "NONE", why[:300])
        self.traded_today.add(s)

    # ---- entry ----
    def _enter(self, s: str, sig: Signal, now: datetime) -> None:
        px, _age = self.cfeed.quote(s)
        stop, target = sig.resolve(px)
        today = now.date()
        chain = self.cfeed.chain(s, today + timedelta(days=self.dte_min), today + timedelta(days=self.dte_max))
        pick, why = pick_vertical(chain, px, sig.side, self.ctx[s].atr14, today,
                                  dte_min=self.dte_min, dte_max=self.dte_max, width_atr=self.width_atr)
        if pick is None:
            return self._none(s, sig, why)
        long_q, short_q = pick
        ts = now.timestamp()
        fill = fill_spread([(long_q, True), (short_q, False)], now=ts)
        if not fill.ok:
            return self._none(s, sig, fill.reason)
        per_spread = fill.net_debit * CONTRACT_MULTIPLIER
        if per_spread <= 0:
            return self._none(s, sig, f"no debit to pay ({fill.net_debit:.2f}); spread mispriced")
        cap = float(self.bot.risk._lim("max_premium_usd"))
        qty = min(int((self.risk_pct * self.equity) // per_spread), int(cap // per_spread))
        if qty <= 0:
            return self._none(s, sig, f"size 0 (one spread costs ${per_spread:,.0f})")
        legs = [Order(side="BUY_TO_OPEN", qty=qty, type="LMT", symbol=long_q.occ, ref_price=long_q.mid,
                      quote_age_s=max(0.0, ts - long_q.quote_time), multiplier=CONTRACT_MULTIPLIER),
                Order(side="SELL_TO_OPEN", qty=qty, type="LMT", symbol=short_q.occ, ref_price=short_q.mid,
                      quote_age_s=max(0.0, ts - short_q.quote_time), multiplier=CONTRACT_MULTIPLIER)]
        with self.bot.L.transaction():
            r = self.bot.risk.pre_trade_spread(legs, net_debit=fill.net_debit)
            if not r.ok:
                return self._none(s, sig, f"rejected: {r.reason}")
            for o, fpx, q in zip(legs, fill.prices, (long_q, short_q), strict=True):
                oid = self.bot.L.order(self.bot.m.id, side=o.side, qty=qty, type_="LMT", symbol=o.symbol, status="sent",
                                       reason=sig.reason, risk_result=r.to_dict(), broker_order_id=f"paper-{now_iso()}", ref_price=q.mid)
                self.bot.record_fill(oid, qty, fpx, q.mid)
            self.bot.set_position(long_q.occ, qty, fill.prices[0], now_iso(), 0, None, "LONG")
            self.bot.set_position(short_q.occ, -qty, fill.prices[1], now_iso(), 0, None, "SHORT")
            pos = OpenSpread(s, sig.side, qty, px, stop, target, now_iso(), None, expiry=long_q.expiry.isoformat(),
                             right=long_q.right, legs=[long_q.occ, short_q.occ], entry_prices=list(fill.prices),
                             net_debit=fill.net_debit, und_entry=px, net_delta=(long_q.delta or 0.0) - (short_q.delta or 0.0))
            self.open[s] = pos
            self.traded_today.add(s)
            self.bot.L.x("INSERT INTO kv(key,value_json,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET "
                         "value_json=excluded.value_json, updated_at=excluded.updated_at",
                         (self._kv_key(s), json.dumps(asdict(pos)), now_iso()))
            self.bot.L.decision(self.bot.m.id, "session", {
                "symbol": s, "px": px, "stop": stop, "legs": [q.occ.strip() for q in (long_q, short_q)], "qty": qty,
                "net_debit": fill.net_debit, "net_delta": round(pos.net_delta, 3), "dte": (long_q.expiry - today).days}, "ENTER", sig.reason)
            self._record_live(pos, long_q, short_q, now)

        # ---- exit ----
    def _exit(self, pos: OpenPos, px: float, age: float, reason: str) -> None:
        if not isinstance(pos, OpenSpread):
            return super()._exit(pos, px, age, reason)
        now = self._now()
        exp = date.fromisoformat(pos.expiry)
        try:
            by_occ = {q.occ: q for q in self.cfeed.chain(pos.symbol, exp, exp)}
        except Exception as e:  # noqa: BLE001 — no chain: keep the spread, retry next poll; after the bell, price at intrinsic
            if now.hour * 60 + now.minute < CLOSE_MIN + 10:
                self.bot.L.decision(self.bot.m.id, "session", {"symbol": pos.symbol}, "NOQUOTE", f"chain: {type(e).__name__}"[:200])
                return
            by_occ = {}
        prices: list[float] = []
        how: list[str] = []
        for occ, sign in zip(pos.legs, (+1, -1), strict=True):
            q = by_occ.get(occ)
            selling = sign > 0                       # closing the long leg sells it; the short leg is bought back
            if q is None:
                prices.append(intrinsic(occ, px))
                how.append("intrinsic (no quote)")
                continue
            p, why = paper_fill_price(q, buying=not selling, now=now.timestamp())
            if p is None:                            # cannot price fairly: take the worst side of the market
                p = q.bid if selling else q.ask
                how.append(f"far side ({why})")
            else:
                how.append("mid +/- 25% spread")
            prices.append(max(0.0, p))
        close = [Order(side="SELL_TO_CLOSE", qty=pos.qty, type="MKT", symbol=pos.legs[0], ref_price=prices[0],
                       quote_age_s=age, reduces_risk=True, multiplier=CONTRACT_MULTIPLIER),
                 Order(side="BUY_TO_CLOSE", qty=pos.qty, type="MKT", symbol=pos.legs[1], ref_price=prices[1],
                       quote_age_s=age, reduces_risk=True, multiplier=CONTRACT_MULTIPLIER)]
        with self.bot.L.transaction():
            r = self.bot.risk.pre_trade_spread(close, net_debit=0.0)          # risk-reducing: always allowed, audited
            for o, fpx in zip(close, prices, strict=True):
                oid = self.bot.L.order(self.bot.m.id, side=o.side, qty=pos.qty, type_="MKT", symbol=o.symbol, status="sent",
                                       reason=reason, risk_result=r.to_dict(), broker_order_id=f"paper-{now_iso()}", ref_price=fpx)
                self.bot.record_fill(oid, pos.qty, fpx, fpx)
                self.bot.set_position(o.symbol, 0)
            pnl = spread_pnl(entry=pos.entry_prices, exit=prices, signs=[+1, -1], qty=pos.qty)
            share_equiv = round(pos.net_delta * CONTRACT_MULTIPLIER * pos.qty * (px - pos.und_entry), 2)
            self.realized += pnl
            net_credit = round(prices[0] - prices[1], 4)
            tid = self.bot.record_trade(entry_at=pos.entry_at, exit_at=now_iso(), qty=pos.qty, entry_px=pos.net_debit,
                                        exit_px=net_credit, bars=0, exit_reason=reason, pnl=pnl, slippage=0.0)
            self.bot.L.x("""INSERT INTO option_trades(trade_id,bot_id,underlying,expiry,right,legs_json,qty,net_debit,net_credit,
                            und_entry,und_exit,net_delta,spread_pnl,share_equiv_pnl,close_method,at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                         (tid, self.bot.m.id, pos.symbol, pos.expiry, pos.right, json.dumps(pos.legs), pos.qty, pos.net_debit, net_credit,
                          pos.und_entry, px, pos.net_delta, pnl, share_equiv, "; ".join(how), now_iso()))
            self.bot.L.x("DELETE FROM kv WHERE key=?", (self._kv_key(pos.symbol),))
            self.bot.L.x("DELETE FROM kv WHERE key=?", (self._live_key(pos.symbol),))
            self._live_at.pop(pos.symbol, None)
            self.bot.L.decision(self.bot.m.id, "session", {"symbol": pos.symbol, "px": px, "pnl": pnl, "share_equiv": share_equiv,
                                                           "close": how}, "EXIT", reason)
            del self.open[pos.symbol]
