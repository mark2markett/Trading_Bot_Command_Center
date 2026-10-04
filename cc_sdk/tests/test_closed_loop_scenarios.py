"""Closed-loop assertions exercise the actual strategy/risk/fill code."""
from pathlib import Path

import pytest

from scripts.closed_loop_guard import sandbox_env
from scripts.closed_loop_scenarios import make_scenarios, run_daily_lifecycle, run_equity, run_spread
from scripts.closed_loop_scenarios import DAY, ScriptedFeed
from scripts.closed_loop_sources import load_sources
from scripts.closed_loop_guard import SandboxError

ROOT = Path(__file__).resolve().parents[2]


def test_source_loading_refuses_mismatched_runtime_before_writing(tmp_path, monkeypatch):
    monkeypatch.setenv("CC_VAR", str(tmp_path / "first" / "var"))
    monkeypatch.setenv("MODE", "paper")
    with pytest.raises(SandboxError):
        load_sources(ROOT, tmp_path / "second" / "var")
    assert not (tmp_path / "first").exists()


@pytest.fixture
def context(tmp_path, monkeypatch):
    runtime = tmp_path / "sandbox" / "var"
    for key, value in sandbox_env(ROOT, runtime).items():
        monkeypatch.setenv(key, value)
    before = {p: p.read_bytes() for p in (ROOT / "bots").rglob("*") if p.is_file() and p.suffix in {".py", ".log"}}
    ctx = make_scenarios(ROOT, runtime)
    assert all(p.read_bytes() == content for p, content in before.items())
    yield ctx
    ctx.close()


def test_actual_gap_rules_make_no_entry_without_a_breakout(context):
    from cc_sdk.intraday import SessionRunner
    feed = ScriptedFeed(breakout=False)
    bot = context.bots["gap_go"]
    runner = SessionRunner(bot, feed, context.modules["gap_go"].GapGoRules(), ["SPY"], adopt_positions=False)
    runner.prepare(DAY)
    runner.step(feed.clock)
    assert runner.open == {} and bot.positions() == []
    assert not bot.L.one("SELECT 1 FROM orders WHERE bot_id='gap_go'")


def test_actual_five_manifests_are_registered_without_source_writes(context):
    assert set(context.bots) == {"gap_go", "nr7", "sip_orb", "spy_mr", "gap_go_spread"}
    assert {b.m.mode for b in context.bots.values()} == {"paper"}
    assert context.daily.HERE.is_relative_to(context.runtime.parent)
    assert not (context.runtime.parent / "bots").exists()


@pytest.mark.parametrize("bot_id", ["gap_go", "nr7", "sip_orb"])
def test_actual_equity_rules_entry_fill_and_exit(context, bot_id):
    evidence = run_equity(context, bot_id)
    bot = context.bots[bot_id]
    assert bot.positions() == []
    assert bot.L.one("SELECT COUNT(*) n FROM trades WHERE bot_id=?", (bot_id,))["n"] == 1
    assert bot.L.one("SELECT COUNT(*) n FROM fills WHERE bot_id=?", (bot_id,))["n"] == 2
    assert "trade" in evidence


def test_actual_gap_go_spread_signal_opens_real_legs_and_greeks(context):
    run_spread(context)
    bot = context.bots["gap_go_spread"]
    assert len(bot.positions()) == 2
    pos = context.runners["gap_go_spread"].open["SPY"]
    assert pos.right == "C" and pos.qty > 0
    assert bot.L.one("SELECT 1 FROM kv WHERE key='optlive:gap_go_spread:SPY'")
    assert bot.L.one("SELECT reason FROM decisions WHERE bot_id='gap_go_spread' AND action='ENTER'")["reason"].startswith("gap +")


def test_stale_chain_refused_with_a_persisted_decision(context):
    run_spread(context, stale=True)
    bot = context.bots["gap_go_spread"]
    assert bot.positions() == []
    assert "old" in bot.L.one("SELECT reason FROM decisions WHERE bot_id='gap_go_spread' AND action='NONE'")["reason"]


def test_daily_bot_runs_decide_reconcile_and_records_a_closed_trade(context):
    run_daily_lifecycle(context)
    bot = context.bots["spy_mr"]
    assert not bot.positions()
    assert bot.L.one("SELECT COUNT(*) n FROM fills WHERE bot_id='spy_mr'")["n"] == 2
    assert bot.L.one("SELECT exit_reason FROM trades WHERE bot_id='spy_mr'")["exit_reason"] == "exit_sma"


def test_daily_protective_stop_is_reconciled(context):
    run_daily_lifecycle(context, crash=True)
    bot = context.bots["spy_mr"]
    assert not bot.positions()
    assert bot.L.one("SELECT exit_reason FROM trades WHERE bot_id='spy_mr'")["exit_reason"] == "crash_stop"
