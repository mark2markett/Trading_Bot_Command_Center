"""The 'live vs backtest' band is drawn only from measured backtest stats, never from invented defaults."""
from cc_server import parity


def test_band_from_measured_stats():
    band = parity.expected_path({"win_rate": 0.52, "avg_win": 0.0056, "avg_loss": -0.0038}, 5, 100_000.0, 0.1)
    assert len(band["median"]) == 5 and band["median"][0] == 100_000.0 and band["median"][-1] > 100_000.0


def test_no_band_without_measured_stats():
    # gap_go_spread: "NOT backtested as options yet" — a band here would be made-up numbers (wr 0.5, ±1%)
    for bt in ({}, {"trades_per_year": 31, "source": "not backtested"}, {"win_rate": 0.5, "avg_win": 0.01}):
        assert parity.expected_path(bt, 5, 100_000.0, 0.1) == {"median": [], "lo": [], "hi": []}
