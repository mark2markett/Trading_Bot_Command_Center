"""Bot manifest: what a bot declares about itself. Validated once at Bot() construction."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

_ID = re.compile(r"^[a-z][a-z0-9_]{1,40}$")

DEFAULT_LIMITS: dict[str, Any] = {
    "max_order_usd": 150_000,
    "max_order_qty": 2_000,
    "max_position_usd": 100_000,
    "max_orders_per_day": 2,
    "max_bot_dd": 0.12,
    "max_consecutive_losses": 4,
    "price_collar_pct": 0.015,
    "stale_quote_s": 90,
}

PORTFOLIO_DEFAULTS: dict[str, Any] = {
    "daily_loss_limit_pct": 0.02,
    "max_gross_exposure": 1.5,
    "dd_pause_pct": 0.06,
    "dd_flatten_pct": 0.08,
    "dd_kill_pct": 0.10,
    "heartbeat_grace_min": 10,
}


@dataclass
class BotManifest:
    id: str
    name: str
    version: str
    strategy_line: str
    instrument: str
    mode: str  # 'paper' | 'live'
    cadence: dict[str, str] = field(default_factory=dict)  # run name -> "HH:MM" ET
    backtest: dict[str, Any] = field(default_factory=dict)
    limits: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not _ID.match(self.id):
            raise ValueError(f"bot id {self.id!r} must match {_ID.pattern}")
        if self.mode not in ("paper", "live"):
            raise ValueError("mode must be 'paper' or 'live'")
        for k, v in self.cadence.items():
            if not re.match(r"^\d{2}:\d{2}$", v):
                raise ValueError(f"cadence {k}={v!r} must be HH:MM")
        merged = dict(DEFAULT_LIMITS)
        merged.update(self.limits)
        self.limits = merged

    def to_row(self) -> dict[str, Any]:
        d = asdict(self)
        return d
