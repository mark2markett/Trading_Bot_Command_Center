"""Gap-and-go paper bot on SPY and QQQ. Research: docs/RESEARCH_RESULTS.md (SPX PF 1.75 / NAS PF 1.44, 2005–2020, 5/5 folds).
Run:  python bot.py session | replay 2020-03-16 [SPY] | status"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cc_sdk"))  # repo checkout without `pip install -e .`
from cc_sdk.intraday_cli import main
from gap_go_rules import GapGoRules

from cc_sdk import BotManifest  # noqa: E402

HERE = Path(__file__).resolve().parent
try:
    from dotenv import load_dotenv

    load_dotenv(HERE / ".env")
except ImportError:
    pass
GAP_BPS = float(os.getenv("GAP_BPS", "70"))
WAIT_MIN = int(os.getenv("WAIT_MIN", "30"))
SYMBOLS = os.getenv("SYMBOLS", "SPY,QQQ").split(",")

MANIFEST = BotManifest(
    id="gap_go", name="Gap-and-Go SPY/QQQ", version="0.1",
    strategy_line=f"gap ≥ {GAP_BPS:.0f} bp · break of {WAIT_MIN}-min range in gap direction · stop at range · flat at close",
    instrument="SPY,QQQ", mode="paper",
    cadence={"session": "09:25"},
    backtest={"win_rate": 0.52, "profit_factor": 1.75, "avg_win": 0.0056, "avg_loss": -0.0038, "trades_per_year": 31,
              "slippage_assumed": 0.0001, "max_dd": 0.072, "source": "research/strategies.py gap_go, SPX500 CFD 2005–2020"},
    limits={"max_position_usd": 50_000, "max_orders_per_day": 4},
)

if __name__ == "__main__":
    main(MANIFEST, lambda: GapGoRules(GAP_BPS, WAIT_MIN), SYMBOLS, HERE, replay_map={"SPY": "SPX500_USD", "QQQ": "NAS100_USD"})
