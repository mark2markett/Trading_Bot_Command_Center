"""NR7 breakout watch-list paper bot (SPY, IWM). Did NOT meet the research bar (PF 1.26–1.29, 4/5 folds); runs on paper
to collect out-of-sample evidence only. Run:  python bot.py session | replay 2020-03-16 [SPY] | status"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cc_sdk"))  # repo checkout without `pip install -e .`
from cc_sdk.intraday_cli import main
from nr7_rules import NR7Rules

from cc_sdk import BotManifest  # noqa: E402

HERE = Path(__file__).resolve().parent
try:
    from dotenv import load_dotenv

    load_dotenv(HERE / ".env")
except ImportError:
    pass
SYMBOLS = os.getenv("SYMBOLS", "SPY,IWM").split(",")

MANIFEST = BotManifest(
    id="nr7", name="NR7 Breakout (watch list)", version="0.1",
    strategy_line="narrowest-range-of-7 day · break of prior high/low · stop 0.25 ATR · target 2R · flat at close",
    instrument="SPY,IWM", mode="paper", cadence={"session": "09:25"},
    backtest={"win_rate": 0.42, "profit_factor": 1.27, "avg_win": 0.0032, "avg_loss": -0.0017, "trades_per_year": 36,
              "slippage_assumed": 0.0001, "max_dd": 0.09, "source": "research nr7_breakout, SPX500/US2000 CFD 2005–2020 — below bar"},
    limits={"max_position_usd": 25_000, "max_orders_per_day": 4},
)

if __name__ == "__main__":
    main(MANIFEST, NR7Rules, SYMBOLS, HERE, replay_map={"SPY": "SPX500_USD", "IWM": "US2000_USD"}, risk_pct=0.005)
