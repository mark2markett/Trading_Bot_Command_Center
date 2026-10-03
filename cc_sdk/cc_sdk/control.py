"""Control flags as files. Bots read these with no database dependency. Missing directory => KILLED (fail closed)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .ledger import var_dir


def control_dir() -> Path:
    return var_dir() / "control"


class Control:
    def __init__(self, bot_id: str, cdir: Path | None = None):
        self.bot_id = bot_id
        self.dir = cdir or control_dir()

    # ---- state ----
    def dir_ok(self) -> bool:
        return self.dir.is_dir()

    def fleet_killed(self) -> bool:
        return (not self.dir_ok()) or (self.dir / "KILL").exists()

    def bot_killed(self) -> bool:
        return (not self.dir_ok()) or (self.dir / f"{self.bot_id}.kill").exists()

    def killed(self) -> bool:
        return self.fleet_killed() or self.bot_killed()

    def entries_paused(self) -> bool:
        return (not self.dir_ok()) or (self.dir / "PAUSE_ENTRIES").exists() or (self.dir / f"{self.bot_id}.pause").exists()

    def flatten_requested(self) -> bool:
        return (self.dir / f"{self.bot_id}.flatten").exists()

    def clear_flatten(self) -> None:
        p = self.dir / f"{self.bot_id}.flatten"
        if p.exists():
            p.unlink()

    def status_word(self) -> str:
        if self.killed():
            return "killed"
        if self.entries_paused():
            return "paused"
        return "running"

    # ---- writes (used by SDK auto-pause and by the server) ----
    @staticmethod
    def write_flag(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), **payload}
        path.write_text(json.dumps(payload, indent=2))

    def pause_bot(self, reason: str, actor: str = "sdk") -> None:
        self.write_flag(self.dir / f"{self.bot_id}.pause", {"actor": actor, "reason": reason})

    @staticmethod
    def read_flag(path: Path) -> dict[str, Any] | None:
        try:
            return json.loads(path.read_text()) if path.exists() else None
        except Exception:  # noqa: BLE001
            return {"raw": True}
