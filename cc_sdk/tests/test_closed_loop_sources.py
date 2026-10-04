"""Real replay plumbing against labeled synthetic parquet fixtures, plus missing-input behavior."""
from pathlib import Path

import pandas as pd
import pytest

from scripts.closed_loop_guard import sandbox_env
from scripts.closed_loop_report import NotCovered, Report
from scripts.closed_loop_scenarios import make_scenarios
from scripts.closed_loop_sources import check_data, replay_one

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def context(tmp_path, monkeypatch):
    runtime = tmp_path / "sandbox" / "var"
    for key, value in sandbox_env(ROOT, runtime).items():
        monkeypatch.setenv(key, value)
    ctx = make_scenarios(ROOT, runtime)
    ctx.repo = tmp_path / "historical-source"
    yield ctx
    ctx.close()


def history(context, *, signal):
    frames = []
    for i, day in enumerate(pd.date_range("2020-01-01", periods=40, tz="America/New_York")):
        index = pd.date_range(day + pd.Timedelta(hours=9, minutes=30), periods=390, freq="min")
        price = 570.0 if signal and i == 39 else 565.0
        frame = pd.DataFrame({"open": price, "high": price + 1, "low": price - 1,
                              "close": price, "volume": 1000}, index=index)
        if signal and i == 39:
            frame.iloc[30:, frame.columns.get_loc("close")] = 572.0
            frame.iloc[30:, frame.columns.get_loc("high")] = 572.5
        frames.append(frame)
    path = context.repo / "var" / "data" / "SPX500_USD_1m_rth.parquet"
    path.parent.mkdir(parents=True)
    pd.concat(frames).to_parquet(path)
    return path


def test_missing_history_is_not_covered(context):
    with pytest.raises(NotCovered, match="absent"):
        replay_one(context, "gap_go", "SPY", "SPX500_USD", max_days=250)
    assert not (context.repo / "var").exists()


def test_zero_signal_window_does_not_pass(context):
    history(context, signal=False)
    with pytest.raises(NotCovered, match="5 trading days"):
        replay_one(context, "gap_go", "SPY", "SPX500_USD", max_days=5)
    assert not context.bots["gap_go"].L.one("SELECT 1 FROM trades WHERE bot_id='gap_go'")


def test_actual_replay_records_orders_fills_trades_without_changing_source(context):
    path = history(context, signal=True)
    before = path.read_bytes()
    evidence = replay_one(context, "gap_go", "SPY", "SPX500_USD", max_days=5)
    assert path.read_bytes() == before
    assert "2020-02-09" in evidence and "orders" in evidence and "fills" in evidence
    bot = context.bots["gap_go"]
    assert bot.L.one("SELECT COUNT(*) n FROM trades WHERE bot_id='gap_go'")["n"] > 0


def test_corrupt_available_history_is_a_failure(context):
    path = context.repo / "var" / "data" / "SPX500_USD_1m_rth.parquet"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"corrupt parquet")
    report = Report()
    report.check("history", lambda: replay_one(context, "gap_go", "SPY", "SPX500_USD"))
    assert report.rows[0]["outcome"] == "FAIL"


def test_missing_injected_auth_reports_gaps_without_dotenv_reads(context, monkeypatch):
    for key in ("POLYGON_API_KEY", "CC_TOKEN_BROKER_URL", "CC_TOKEN_BROKER_SECRET", "SUPABASE_URL"):
        monkeypatch.delenv(key, raising=False)
    import dotenv
    def forbidden(*args, **kwargs):
        pytest.fail("No credential-file loading allowed")
    monkeypatch.setattr(dotenv, "load_dotenv", forbidden)
    report = Report()
    check_data(context, report)
    assert len(report.rows) == 2
    assert all(row["outcome"] == "NOT COVERED" for row in report.rows)
