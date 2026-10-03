"""Integration: server + template bot in a temp var/. Kill path, silence detection, ladder, parity drift, limits audit."""
import importlib
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "cc_sdk"))
sys.path.insert(0, str(ROOT / "cc_server"))


@pytest.fixture()
def env(tmp_path, monkeypatch):
    var = tmp_path / "var"; (var / "control").mkdir(parents=True)
    monkeypatch.setenv("CC_VAR", str(var))
    # fresh modules so the module-level ledger picks up CC_VAR
    for m in list(sys.modules):
        if m.startswith("cc_server") or m.startswith("cc_sdk"):
            sys.modules.pop(m)
    import cc_server.api as api
    import cc_server.main as main
    import cc_server.riskd as riskd
    from cc_sdk.ledger import Ledger
    importlib.reload(api)
    client = TestClient(main.app)
    return {"var": var, "client": client, "api": api, "riskd": riskd, "L": Ledger(var / "cc.db")}


def run_template(var: Path, cmd: str) -> None:
    env = {**os.environ, "CC_VAR": str(var), "PYTHONPATH": str(ROOT / "cc_sdk")}
    subprocess.run([sys.executable, str(ROOT / "bots/_template_bot/bot.py"), cmd], check=True, env=env, timeout=30)


def test_kill_path_end_to_end(env):
    var, c, L = env["var"], env["client"], env["L"]
    run_template(var, "decide")                       # opens a paper position of 10 SPY
    assert L.one("SELECT qty FROM positions WHERE bot_id='template'")["qty"] == 10
    t0 = time.time()
    r = c.post("/api/controls/kill_all", json={"word": "wrong"}); assert r.status_code == 400
    assert not (var / "control" / "KILL").exists()
    word = c.post("/api/controls/confirm/kill_all").json()["word"]
    r = c.post("/api/controls/kill_all", json={"word": word, "note": "test"}); assert r.status_code == 200
    assert (var / "control" / "KILL").exists()
    # audit row exists and was written BEFORE the flag file
    ctl = L.one("SELECT at FROM controls WHERE action='kill_all'")
    assert ctl is not None
    flag_mtime = datetime.fromtimestamp((var / "control" / "KILL").stat().st_mtime, tz=timezone.utc)
    assert datetime.fromisoformat(ctl["at"]) <= flag_mtime + timedelta(seconds=1)
    assert L.one("SELECT 1 FROM alerts WHERE kind='kill' AND severity='page'")
    # bot's next run flattens through its own path and clears the flag
    run_template(var, "decide")
    assert L.one("SELECT qty FROM positions WHERE bot_id='template'")["qty"] == 0
    assert not (var / "control" / "template.flatten").exists()
    fleet = c.get("/api/fleet").json()
    assert fleet["killed"] and any(b["status"] == "killed" for b in fleet["bots"])
    assert time.time() - t0 < 5.0
    # new entry blocked while killed
    run_template(var, "decide")
    assert L.one("SELECT COUNT(*) n FROM orders WHERE status='rejected'")["n"] >= 1
    # re-arm
    word = c.post("/api/controls/confirm/rearm").json()["word"]
    assert c.post("/api/controls/rearm", json={"word": word, "note": "drill over"}).status_code == 200
    assert not (var / "control" / "KILL").exists()
    assert c.get("/api/fleet").json()["killed"] is False


def test_silence_is_failure(env, monkeypatch):
    L, riskd = env["L"], env["riskd"]
    from cc_sdk import Bot, BotManifest
    Bot(BotManifest(id="quiet", name="Quiet Bot", version="1", strategy_line="", instrument="SPY", mode="live",
                    cadence={"reconcile": "09:45"}), db_path=L.path, control_dir=env["var"] / "control")
    # pretend it is a Tuesday 10:00 ET with no heartbeat
    fake_now = datetime(2026, 10, 6, 14, 0, tzinfo=timezone.utc)  # 10:00 ET
    flagged = riskd.heartbeat_watch(L, now=fake_now)
    assert "quiet" in flagged
    a = L.one("SELECT severity, message FROM alerts WHERE kind='heartbeat'")
    assert a["severity"] == "page" and "missed" in a["message"]
    # second tick same day does not page again
    riskd.heartbeat_watch(L, now=fake_now + timedelta(minutes=5))
    assert L.one("SELECT COUNT(*) n FROM alerts WHERE kind='heartbeat'")["n"] == 1
    # before grace: not flagged
    assert "quiet" not in riskd.heartbeat_watch(L, now=datetime(2026, 10, 6, 13, 50, tzinfo=timezone.utc))


def test_drawdown_ladder(env):
    L, riskd, var = env["L"], env["riskd"], env["var"]
    from cc_sdk import Bot, BotManifest
    for bid in ("a_bot", "b_bot"):
        Bot(BotManifest(id=bid, name=bid, version="1", strategy_line="", instrument="SPY", mode="paper"),
            db_path=L.path, control_dir=var / "control")
        L.set_position(bid, "SPY", 10, 500, None, 0)
    L.equity("a_bot", 100_000, "broker")
    L.equity("a_bot", 93_500, "broker")      # -6.5%
    assert riskd.apply_ladder(L) == ["pause"]
    assert (var / "control" / "PAUSE_ENTRIES").exists()
    assert riskd.apply_ladder(L) == []        # fires once
    L.equity("a_bot", 91_500, "broker")      # -8.5%
    assert riskd.apply_ladder(L) == ["flatten"]
    assert list((var / "control").glob("*.flatten"))
    L.equity("a_bot", 89_000, "broker")      # -11%
    assert riskd.apply_ladder(L) == ["kill"]
    assert (var / "control" / "KILL").exists()
    acts = [c["action"] for c in env["api"].db.controls(L, 20)]
    assert {"pause_entries", "flatten", "kill_all"} <= set(acts)


def test_parity_drift_and_limit_audit(env):
    L, c = env["L"], env["client"]
    from cc_sdk import Bot, BotManifest
    Bot(BotManifest(id="drifty", name="Drifty", version="1", strategy_line="", instrument="SPY", mode="paper",
                    backtest={"win_rate": 0.73, "avg_win": 0.012, "avg_loss": -0.008, "slippage_assumed": 0.01}),
        db_path=L.path, control_dir=env["var"] / "control")
    for i in range(12):
        win = i % 3 == 0  # 4 wins of 12
        L.trade("drifty", entry_at=f"2026-01-{i+1:02d}", exit_at=f"2026-01-{i+2:02d}", qty=1, entry_px=100,
                exit_px=101 if win else 99.2, bars=2, exit_reason="x", pnl=1 if win else -0.8, slippage=0)
    b = c.get("/api/bots/drifty").json()
    assert b["parity"]["verdict"] == "drift" and "win rate" in b["parity"]["sentence"]
    r = c.put("/api/limits/portfolio/daily_loss_limit_pct", json={"value": 0.025, "note": "test"}).json()
    assert r["before"] == 0.02 and r["after"] == 0.025
    audit = c.get("/api/risk").json()["audit"]
    assert audit[0]["action"] == "limit" and audit[0]["before"] == 0.02 and audit[0]["after"] == 0.025
    assert c.put("/api/limits/portfolio/nonsense", json={"value": 1}).status_code == 400


def test_health_and_fleet_empty(env):
    c = env["client"]
    assert c.get("/api/health").json()["ok"]
    f = c.get("/api/fleet").json()
    assert f["bots"] == [] and f["killed"] is False
