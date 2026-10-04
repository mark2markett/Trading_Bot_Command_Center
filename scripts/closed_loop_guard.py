"""Read-only source inspection and fail-closed sandbox boundaries. No SDK imports."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import uuid4

TABLES = ("trades", "orders", "fills", "option_trades", "decisions", "positions", "controls", "alerts")


class SandboxError(ValueError):
    """An unsafe sandbox configuration; fail before importing code with side effects."""


def validate_sandbox(repo: Path, cc_var: str | None) -> Path:
    if not cc_var or not cc_var.strip():
        raise SandboxError("CC_VAR must point to an external sandbox")
    root = repo.resolve()
    runtime = Path(cc_var).resolve()
    if runtime == root / "var" or runtime == (root / "var").resolve() or runtime.is_relative_to(root) or root.is_relative_to(runtime):
        raise SandboxError("CC_VAR must be outside the checkout and live var directory")
    if runtime == runtime.parent or runtime.is_file():
        raise SandboxError("CC_VAR is not a safe runtime directory")
    if (runtime.parent / "bots").exists():
        raise SandboxError("Sandbox has a sibling bots directory; server controls could spawn bots")
    for name in ("cc.db", "cc.db-wal", "cc.db-shm", "control", "logs", "data", "alerts.toml", "schwab_token.json"):
        entry = runtime / name
        if entry.is_symlink() or getattr(entry, "is_junction", lambda: False)() or not entry.resolve().is_relative_to(runtime):
            raise SandboxError("Sandbox contains an aliased runtime entry")
    return runtime


def sandbox_env(repo: Path, runtime: Path) -> dict[str, str]:
    if os.getenv("MODE", "paper").strip().lower() != "paper":
        raise SandboxError("Inherited MODE must be paper; live mode is refused")
    runtime = validate_sandbox(repo, str(runtime))
    env = dict(os.environ)
    for key in ("LIVE_CONFIRM", "TOKEN_PATH", "SYMBOL", "SYMBOLS", "GAP_BPS", "WAIT_MIN", "DTE_MIN", "DTE_MAX",
                "WIDTH_ATR", "TOP_N", "ALLOCATION_PCT", "MAX_SHARES", "STOP_PCT", "CC_MAX_POSITION_USD"):
        env.pop(key, None)
    env.update(CC_VAR=str(runtime), MODE="paper", PYTHONUTF8="1", PYTHON_DOTENV_DISABLED="1", PYTHONDONTWRITEBYTECODE="1",
               PYTHONPATH=os.pathsep.join(str(repo / p) for p in ("cc_sdk", "cc_server", ".")))
    return env


def claim_run(repo: Path, root: Path) -> str:
    """Claim only a fresh, empty launcher-created directory, before any worker writes."""
    runtime = validate_sandbox(repo, str(root / "var"))
    if list(root.iterdir()):
        raise SandboxError("Run ownership requires an empty directory")
    token = uuid4().hex
    (root / ".closed-loop-owner.json").write_text(json.dumps({"runtime": str(runtime), "token": token}), encoding="utf-8")
    return token


def owned_run(repo: Path, runtime: Path) -> Path:
    runtime = validate_sandbox(repo, str(runtime))
    root = runtime.parent
    marker = root / ".closed-loop-owner.json"
    if runtime.name != "var" or marker.is_symlink() or not marker.is_file():
        raise SandboxError("Worker requires a launcher-owned run directory")
    try:
        owner = json.loads(marker.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise SandboxError("Run ownership metadata invalid") from exc
    if owner.get("runtime") != str(runtime) or not owner.get("token") or owner["token"] != os.getenv("CC_CLOSED_LOOP_OWNER"):
        raise SandboxError("Run ownership token mismatch")
    for entry in root.iterdir():
        if entry.is_symlink() or getattr(entry, "is_junction", lambda: False)() or not entry.resolve().is_relative_to(root):
            raise SandboxError("Owned run contains an aliased entry")
    return root


def fingerprint(live_var: Path) -> dict:
    """Snapshot logical records with a read-only SQLite connection, never Ledger()."""
    db = live_var / "cc.db"
    result = {"available": db.is_file(), "tables": {}, "control": [], "control_exists": (live_var / "control").is_dir(),
              "excluded_tables": ["heartbeats", "kv"]}
    if db.is_file():
        with closing(sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True, timeout=10)) as conn:
            conn.execute("PRAGMA query_only=ON")
            conn.execute("BEGIN")
            existing = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for table in TABLES:
                if table not in existing:
                    result["tables"][table] = {"missing": True}
                    continue
                columns = [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')]
                order = ",".join(str(i + 1) for i in range(len(columns)))
                digest = hashlib.sha256()
                count, maximum = 0, None
                id_index = columns.index("id") if "id" in columns else None
                for row in conn.execute(f'SELECT * FROM "{table}" ORDER BY {order}'):
                    digest.update(json.dumps(row, default=str, separators=(",", ":")).encode())
                    digest.update(b"\n")
                    count += 1
                    if id_index is not None and row[id_index] is not None:
                        maximum = max(maximum or 0, row[id_index])
                result["tables"][table] = {"count": count, "max_id": maximum, "digest": digest.hexdigest()}
    controls = live_var / "control"
    if controls.is_symlink():
        raise SandboxError("Live control directory is a symlink; refusing to follow it")
    if controls.is_dir():
        for path in sorted(controls.rglob("*")):
            if path.is_symlink():
                raise SandboxError("Live control entry is a symlink; refusing to follow it")
            if path.is_file():
                stat = path.stat()
                result["control"].append({"path": path.relative_to(controls).as_posix(), "size": stat.st_size,
                                          "mtime_ns": stat.st_mtime_ns, "digest": hashlib.sha256(path.read_bytes()).hexdigest()})
    return result
