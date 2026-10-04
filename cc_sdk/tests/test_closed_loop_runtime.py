"""Owned-server identity, actual API controls, and failure-cleanup integration checks."""
import socket
import os
from pathlib import Path

import pytest

from scripts.closed_loop_guard import SandboxError, claim_run, sandbox_env
from scripts.closed_loop_report import Report
from scripts.closed_loop_scenarios import make_scenarios, run_equity, run_spread
from scripts.closed_loop_server import start_server
from scripts.closed_loop_controls import check_controls, check_dashboard

ROOT = Path(__file__).resolve().parents[2]


def test_busy_port_is_refused_without_contacting_existing_server(tmp_path):
    with socket.socket() as listener:
        if os.name != "nt":
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 8586))
        listener.listen()
        with pytest.raises(SandboxError, match="8586"):
            start_server(ROOT, tmp_path / "sandbox" / "var")
        listener.settimeout(0.05)
        with pytest.raises(TimeoutError):
            listener.accept()


@pytest.fixture
def running(tmp_path, monkeypatch):
    runtime = tmp_path / "sandbox" / "var"
    runtime.parent.mkdir()
    monkeypatch.setenv("CC_CLOSED_LOOP_OWNER", claim_run(ROOT, runtime.parent))
    for key, value in sandbox_env(ROOT, runtime).items():
        monkeypatch.setenv(key, value)
    context = make_scenarios(ROOT, runtime)
    for bot_id in ("gap_go", "nr7", "sip_orb"):
        run_equity(context, bot_id)
    run_spread(context)
    server = start_server(ROOT, runtime)
    yield context, server
    server.stop()
    assert server.process.poll() is not None
    context.close()


def test_server_identity_and_actual_dashboard_readback(running):
    context, server = running
    server.verify()
    report = Report()
    check_dashboard(context, server, report)
    assert report.exit_code == 0, report.table()
    assert all(r["outcome"] == "PASS" for r in report.rows)


def test_wrong_run_identity_refuses_controls(running):
    _, server = running
    actual = server.nonce
    server.nonce = "wrong-identity"
    try:
        with pytest.raises(SandboxError, match="identity"):
            server.request("POST", "/api/controls/pause_entries", json={"note": "must not execute"})
    finally:
        server.nonce = actual
    assert not (server.runtime / "control" / "PAUSE_ENTRIES").exists()


def test_actual_controls_change_runner_behavior_and_write_audits_first(running):
    context, server = running
    report = Report()
    check_controls(context, server, report)
    assert report.exit_code == 0, report.table()
    assert len(report.rows) >= 7
    assert context.bots["gap_go_spread"].L.one("SELECT 1 FROM option_trades WHERE bot_id='gap_go_spread'")
    assert not (context.runtime / "control" / "KILL").exists()
    audit = (context.runtime / "flag-audit.jsonl").read_text()
    assert '"audit_before_flag": true' in audit


def test_supervisor_can_stop_only_its_orphaned_server(running):
    from scripts.closed_loop_server import stop_orphaned_server
    _, server = running
    stop_orphaned_server(server.runtime)
    assert server.process.wait(timeout=5) is not None
    assert not (server.runtime.parent / "owned-server.json").exists()


def test_orphan_cleanup_refuses_a_foreign_identity(running):
    import json
    from scripts.closed_loop_server import stop_orphaned_server
    _, server = running
    owner = server.runtime.parent / "owned-server.json"
    data = json.loads(owner.read_text())
    data["nonce"] = "foreign"
    owner.write_text(json.dumps(data))
    with pytest.raises(SandboxError, match="identity"):
        stop_orphaned_server(server.runtime)
    assert server.process.poll() is None
