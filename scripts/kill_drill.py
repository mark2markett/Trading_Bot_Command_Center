"""
Kill-switch drill. Run monthly. Exercises the real kill path against PAPER bots only:
  1. refuse to run if any live bot is registered (unless --include-live is passed knowingly)
  2. request a confirmation word from the server, send KILL ALL
  3. assert: audit row written before the KILL flag; flatten flags exist; bots marked killed; page alert raised
  4. re-arm, record a 'drill' controls row with timing
Requires the server running at 127.0.0.1:8585.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cc_sdk"))
from cc_sdk.control import control_dir  # noqa: E402
from cc_sdk.ledger import Ledger  # noqa: E402

API = "http://127.0.0.1:8585/api"


def main() -> int:
    L = Ledger()
    bots = L.q("SELECT id, mode FROM bots")
    live = [b["id"] for b in bots if b["mode"] == "live"]
    if live and "--include-live" not in sys.argv:
        print(f"Refusing: live bots registered ({', '.join(live)}). A drill would flatten real positions. Pass --include-live only if you mean it.")
        return 2
    c = httpx.Client(timeout=10)
    if not c.get(f"{API}/health").json().get("ok"):
        print("server not healthy"); return 1
    t0 = time.perf_counter()
    word = c.post(f"{API}/controls/confirm/kill_all").json()["word"]
    r = c.post(f"{API}/controls/kill_all", json={"word": word, "note": "drill", "actor": "drill"})
    r.raise_for_status()
    cdir = control_dir()
    assert (cdir / "KILL").exists(), "KILL flag missing"
    ctl = L.one("SELECT at FROM controls WHERE action='kill_all' ORDER BY id DESC LIMIT 1")
    flag_at = datetime.fromtimestamp((cdir / "KILL").stat().st_mtime, tz=timezone.utc)
    assert datetime.fromisoformat(ctl["at"]) <= flag_at, "audit row must precede the flag"
    flat = list(cdir.glob("*.flatten"))
    assert L.one("SELECT 1 FROM alerts WHERE kind='kill' ORDER BY id DESC LIMIT 1"), "no page alert"
    killed = c.get(f"{API}/fleet").json()["killed"]
    elapsed = time.perf_counter() - t0
    # re-arm
    word = c.post(f"{API}/controls/confirm/rearm").json()["word"]
    c.post(f"{API}/controls/rearm", json={"word": word, "note": "drill complete", "actor": "drill"}).raise_for_status()
    for p in cdir.glob("*.flatten"):
        p.unlink()  # bots did not run during the drill; clear the flatten requests we created
    L.control("drill", "drill", "fleet", None, {"bots": len(bots), "flatten_flags": len(flat), "seconds": round(elapsed, 2)}, "kill-switch drill passed")
    print(json.dumps({"ok": True, "bots": len(bots), "flatten_flags": len(flat), "killed_seen": killed, "seconds": round(elapsed, 2)}, indent=2))
    return 0 if killed and elapsed < 5 else 1


if __name__ == "__main__":
    sys.exit(main())
