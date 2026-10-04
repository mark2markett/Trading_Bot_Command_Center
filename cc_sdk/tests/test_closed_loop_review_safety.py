"""Regressions for independent review findings, using only disposable state."""
import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from scripts import closed_loop, seed_demo
from scripts.closed_loop_guard import SandboxError
from scripts.closed_loop_report import Report
from scripts.closed_loop_sources import check_data

ROOT = Path(__file__).resolve().parents[2]


def test_worker_refuses_caller_owned_directory_before_scenarios(tmp_path, monkeypatch):
    runtime = tmp_path / "caller" / "var"
    runtime.mkdir(parents=True)
    sentinel = runtime / "keep.txt"
    sentinel.write_text("caller state")
    monkeypatch.setenv("CC_VAR", str(runtime))
    monkeypatch.setenv("MODE", "paper")
    monkeypatch.delenv("CC_CLOSED_LOOP_OWNER", raising=False)
    # Avoid executing the unsafe old worker against caller data while checking the boundary.
    monkeypatch.setattr(closed_loop, "run_worker", lambda *args: 0)
    assert closed_loop.main(["--worker"]) == 2
    assert sentinel.read_text() == "caller state"


@pytest.mark.parametrize("entry", ["cc.db", "cc.db-wal", "cc.db-shm", "control"])
def test_seed_refuses_nested_live_alias_before_opening_ledger(tmp_path, monkeypatch, entry):
    repo, runtime = tmp_path / "repo", tmp_path / "demo/var"
    (repo / "var/control").mkdir(parents=True)
    (repo / "var/cc.db").write_text("untouched fixture")
    if entry in {"cc.db-wal", "cc.db-shm"}:
        (repo / "var" / entry).write_text("untouched sidecar")
    runtime.mkdir(parents=True)
    (runtime / entry).symlink_to(repo / "var" / entry, target_is_directory=entry == "control")
    monkeypatch.setattr(seed_demo, "ROOT", repo)
    monkeypatch.setenv("CC_VAR", str(runtime))
    def forbidden(*args):
        pytest.fail("Alias must be rejected before Ledger opens")
    monkeypatch.setattr(seed_demo, "Ledger", forbidden)
    with pytest.raises(SandboxError):
        seed_demo.main(False)
    assert (repo / "var/cc.db").read_text() == "untouched fixture"


def test_token_broker_is_never_contacted_even_when_injected(tmp_path, monkeypatch):
    from cc_sdk.schwab_feed import SchwabFeed
    monkeypatch.setenv("CC_TOKEN_BROKER_URL", "https://example.invalid/token")
    monkeypatch.setenv("CC_TOKEN_BROKER_SECRET", "fixture-only")
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("POLYGON_API_KEY", raising=False)
    def forbidden(*args):
        pytest.fail("Token broker may refresh remote state and must not be contacted")
    monkeypatch.setattr(SchwabFeed, "from_broker", forbidden)
    report = Report()
    check_data(SimpleNamespace(runtime=tmp_path), report)
    assert all(row["outcome"] == "NOT COVERED" for row in report.rows)
    assert "remote" in report.rows[0]["evidence"]


def test_unreachable_orphan_is_not_treated_as_stopped(tmp_path, monkeypatch):
    from scripts.closed_loop_server import stop_orphaned_server
    runtime = tmp_path / "var"
    runtime.mkdir()
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(20)"])
    owner = tmp_path / "owned-server.json"
    owner.write_text(json.dumps({"pid": process.pid, "nonce": "fixture", "runtime": str(runtime)}))
    def unreachable(*args, **kwargs):
        raise httpx.ConnectError("fixture unreachable")
    monkeypatch.setattr(httpx.Client, "get", unreachable)
    try:
        with pytest.raises(SandboxError, match="stop|exit|identity"):
            stop_orphaned_server(runtime)
        assert process.poll() is None
        assert owner.exists()
    finally:
        process.terminate()
        process.wait(timeout=5)


def test_failed_owned_server_stop_retains_owner_marker(tmp_path):
    from scripts.closed_loop_server import OwnedServer
    runtime = tmp_path / "var"
    owner = tmp_path / "owned-server.json"
    owner.write_text(json.dumps({"nonce": "fixture"}))
    def blocked():
        raise PermissionError("fixture termination blocked")
    process = SimpleNamespace(poll=lambda: None, terminate=blocked)
    resource = SimpleNamespace(close=lambda: None)
    server = OwnedServer(process, runtime, "fixture", resource, resource)
    with pytest.raises(PermissionError):
        server.stop()
    assert owner.exists(), "Failed termination must preserve ownership and runtime"


def test_authenticated_data_request_does_not_log_vendor_cursor_secrets(tmp_path, monkeypatch, caplog):
    from cc_sdk import polygon_options
    secret = "fixture-sentinel-secret"
    monkeypatch.setenv("POLYGON_API_KEY", secret)
    caplog.set_level(logging.INFO, logger="httpx")
    requests = []
    def vendor(request):
        requests.append(request)
        body = {"results": [{"details": {"ticker": "O:SPY261007C00570000"}, "last_quote": {"bid": 1, "ask": 1.02}}]}
        if len(requests) == 1:
            body["next_url"] = "https://api.polygon.io/v3/snapshot/options/SPY?cursor=fixture&apiKey=" + secret
        return httpx.Response(200, json=body)
    monkeypatch.setattr(polygon_options, "polygon_from_env", lambda: polygon_options.PolygonOptions(secret, transport=httpx.MockTransport(vendor)))
    report = Report()
    check_data(SimpleNamespace(runtime=tmp_path), report)
    assert report.rows[1]["outcome"] == "PASS"
    assert len(requests) == 2
    assert secret not in caplog.text


def test_write_audit_blocks_external_changes_and_preserves_read_only_fingerprint(tmp_path):
    run, live = tmp_path / "run", tmp_path / "live"
    run.mkdir()
    live.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("unchanged")
    code = '''
import os, sqlite3, sys
from pathlib import Path
from scripts.closed_loop_guard import SandboxError
from scripts.closed_loop_audit import WriteAudit
run, live, outside = map(Path, sys.argv[1:])
with sqlite3.connect(live / "cc.db") as conn:
    conn.execute("CREATE TABLE fixture (id INTEGER)")
audit = WriteAudit(run, live)
audit.install()
(run / "allowed.txt").write_text("sandbox")
for operation in (lambda: outside.write_text("bad"),
                  lambda: sqlite3.connect(live / "cc.db"),
                  lambda: os.mkdir(outside.parent / "forbidden"),
                  lambda: os.rename(run / "allowed.txt", outside)):
    try:
        operation()
    except SandboxError:
        pass
    else:
        raise AssertionError("External write was permitted")
with sqlite3.connect((live / "cc.db").resolve().as_uri() + "?mode=ro", uri=True) as conn:
    assert conn.execute("SELECT COUNT(*) FROM fixture").fetchone()[0] == 0
assert audit.blocked == 4
assert outside.read_text() == "unchanged"
'''
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(ROOT))
    result = subprocess.run([sys.executable, "-c", code, str(run), str(live), str(outside)],
                            env=env, cwd=ROOT, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    rows = [json.loads(line) for line in (run / "write-audit-worker.jsonl").read_text().splitlines()]
    assert any(row["event"] == "sqlite3.connect" and row["outcome"] == "blocked" for row in rows)
    assert outside.read_text() == "unchanged"
