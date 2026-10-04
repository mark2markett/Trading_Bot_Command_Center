"""Supervisor/worker, failure cleanup, and truthful function reachability."""
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.closed_loop import main, run_worker
from scripts.closed_loop_guard import sandbox_env
from scripts.closed_loop_report import FunctionInventory, Report

ROOT = Path(__file__).resolve().parents[2]


def test_worker_refuses_unset_cc_var_without_side_effects(monkeypatch):
    monkeypatch.delenv("CC_VAR", raising=False)
    result = subprocess.run([sys.executable, str(ROOT / "scripts/closed_loop.py"), "--worker"],
                            capture_output=True, text=True, env=dict(os.environ), timeout=10)
    assert result.returncode != 0
    assert "CC_VAR" in result.stderr


def test_supervisor_refuses_unsafe_caller_and_live_mode(monkeypatch):
    monkeypatch.setenv("CC_VAR", str(ROOT / "var"))
    assert main([]) == 2
    monkeypatch.delenv("CC_VAR")
    monkeypatch.setenv("MODE", "live")
    assert main([]) == 2


def test_function_inventory_keeps_uncalled_functions_as_gaps(tmp_path):
    source = tmp_path / "cc_sdk/cc_sdk/sample.py"
    source.parent.mkdir(parents=True)
    source.write_text("def called():\n    return 1\ndef not_called():\n    return 2\n")
    spec = importlib.util.spec_from_file_location("inventory_sample", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    inventory = FunctionInventory(tmp_path)
    with inventory.observe("scenario assertion"):
        assert module.called() == 1
    rows = inventory.rows()
    assert next(r for r in rows if r["name"].endswith("called") and not r["name"].endswith("not_called"))["scenarios"] == ["scenario assertion"]
    assert next(r for r in rows if r["name"].endswith("not_called"))["scenarios"] == []


def test_failed_scenario_still_reports_and_cleans_up(tmp_path, monkeypatch):
    runtime = tmp_path / "sandbox" / "var"
    for key, value in sandbox_env(ROOT, runtime).items():
        monkeypatch.setenv(key, value)
    from scripts import closed_loop
    def fail(context, server, report):
        report.add("Deliberate regression", "FAIL", "Injected test assertion", synthetic=True)
    monkeypatch.setattr(closed_loop, "check_controls", fail)
    monkeypatch.setattr(closed_loop, "capture_web", lambda *args: None)
    assert run_worker(ROOT, runtime) == 1
    assert not runtime.exists()
    report = (runtime.parent / "report.md").read_text()
    assert "Deliberate regression" in report and "FAIL" in report
    assert "Before" in report and "After" in report


def test_cleanup_failure_is_reported_and_cannot_return_success(tmp_path, monkeypatch):
    runtime = tmp_path / "sandbox" / "var"
    for key, value in sandbox_env(ROOT, runtime).items():
        monkeypatch.setenv(key, value)
    from scripts import closed_loop
    monkeypatch.setattr(closed_loop, "capture_web", lambda *args: None)
    def locked(*args, **kwargs):
        raise PermissionError("simulated locked state")
    monkeypatch.setattr(closed_loop, "remove_runtime", locked)
    assert run_worker(ROOT, runtime) == 1
    assert runtime.exists()
    assert "Runtime cleanup" in (runtime.parent / "report.md").read_text()


def test_interruption_still_closes_server_and_records_failure(tmp_path, monkeypatch):
    runtime = tmp_path / "sandbox" / "var"
    for key, value in sandbox_env(ROOT, runtime).items():
        monkeypatch.setenv(key, value)
    from scripts import closed_loop
    def interrupt(*args):
        raise KeyboardInterrupt
    monkeypatch.setattr(closed_loop, "check_controls", interrupt)
    monkeypatch.setattr(closed_loop, "capture_web", lambda *args: None)
    try:
        result = run_worker(ROOT, runtime)
    except KeyboardInterrupt:
        pytest.fail("Interruption was not recorded as a failed run")
    assert result == 1
    assert not runtime.exists()
    assert "KeyboardInterrupt" in (runtime.parent / "report.md").read_text()
