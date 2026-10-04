"""Isolation tests use disposable directories, never the production var tree."""
import json
import sqlite3
from pathlib import Path

import pytest

from scripts.closed_loop_guard import SandboxError, fingerprint, sandbox_env, validate_sandbox
from scripts.closed_loop_report import Report


@pytest.mark.parametrize("value", [None, "", ".", "var", "var/nested", "../repo/var"])
def test_guard_refuses_unset_or_checkout_paths(tmp_path, monkeypatch, value):
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.chdir(repo)
    with pytest.raises(SandboxError):
        validate_sandbox(repo, value)
    assert list(repo.iterdir()) == []


def test_guard_follows_symlinks_before_validation(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(repo, target_is_directory=True)
    with pytest.raises(SandboxError):
        validate_sandbox(repo, str(alias / "var"))


def test_guard_rejects_sibling_bot_executables(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    bot = tmp_path / "sandbox" / "bots" / "x" / "bot.py"
    bot.parent.mkdir(parents=True)
    bot.write_text("raise RuntimeError('must not run')")
    with pytest.raises(SandboxError):
        validate_sandbox(repo, str(bot.parents[2] / "var"))


def test_external_sandbox_environment_is_paper(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    runtime = tmp_path / "sandbox" / "var"
    assert validate_sandbox(repo, str(runtime)) == runtime.resolve()
    monkeypatch.setenv("MODE", "paper")
    env = sandbox_env(repo, runtime)
    assert env["MODE"] == "paper" and env["CC_VAR"] == str(runtime.resolve())
    assert env["PYTHONUTF8"] == "1"
    monkeypatch.setenv("MODE", "live")
    with pytest.raises(SandboxError):
        sandbox_env(repo, runtime)


def test_fingerprint_handles_positions_and_detects_updates(tmp_path):
    live = tmp_path / "live"
    live.mkdir()
    db = live / "cc.db"
    with sqlite3.connect(db) as c:
        c.execute("CREATE TABLE positions(bot_id TEXT, symbol TEXT, qty INTEGER)")
        c.execute("INSERT INTO positions VALUES('spy_mr','SPY',10)")
        c.execute("CREATE TABLE trades(id INTEGER PRIMARY KEY, pnl REAL)")
        c.execute("INSERT INTO trades VALUES(1,2.5)")
    controls = live / "control"
    controls.mkdir()
    (controls / "KILL").write_text('{"actor":"test"}')
    original = db.read_bytes()
    before = fingerprint(live)
    assert before["available"]
    assert before["tables"]["positions"]["count"] == 1
    assert before["tables"]["positions"]["max_id"] is None
    assert before["tables"]["trades"]["max_id"] == 1
    assert db.read_bytes() == original
    assert fingerprint(live) == before
    with sqlite3.connect(db) as c:
        c.execute("UPDATE positions SET qty=9")
    after = fingerprint(live)
    assert after["tables"]["positions"]["digest"] != before["tables"]["positions"]["digest"]
    (controls / "KILL").write_text('{"actor":"other"}')
    assert fingerprint(live)["control"] != after["control"]


def test_absent_live_state_is_unavailable_without_creating_it(tmp_path):
    live = tmp_path / "absent"
    assert fingerprint(live)["available"] is False
    assert not live.exists()


def test_report_distinguishes_failures_gaps_and_synthetic(tmp_path):
    report = Report()
    report.add("options", "PASS", "2 legs", synthetic=True)
    report.add("history", "NOT COVERED", "no parquet")
    assert report.exit_code == 0
    report.add("isolation", "FAIL", "position changed")
    assert report.exit_code == 1
    report.before = {"available": False}
    report.after = {"available": False}
    path = tmp_path / "report.md"
    report.write(path)
    text = path.read_text()
    assert "1 FAIL" in text and "1 NOT COVERED" in text and "SYNTHETIC" in text
    assert "before" in text.lower() and "after" in text.lower()
    with pytest.raises(ValueError):
        report.add("unknown", "SKIP", "invalid outcome")
    assert json.loads((tmp_path / "report.json").read_text())["rows"][1]["outcome"] == "NOT COVERED"
