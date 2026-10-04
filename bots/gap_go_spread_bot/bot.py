"""Gap-and-go as a same-day debit vertical on SPY and QQQ (M7.5, docs/06_OPTIONS_M7_SPEC.md). Paper only.

The signal is gap_go's, unchanged (bots/gap_go_bot/gap_go_rules.py): gap >= 70 bp, then a break of the first 30-minute
range in the gap direction. Up-gap -> call debit spread, down-gap -> put debit spread. Expiry 2-7 days out; long leg
nearest the money, short leg one ATR further. Closed the same day at gap_go's stop (judged on the underlying) or at
15:58 ET. These are starting values, not tuned ones.
Data: the underlying from Schwab, option quotes from Polygon real-time (owner decision 2026-10-04).

The spread is NOT yet backtested as options (M7.6). `python bot.py report` says whether it beats the same delta held in
shares; until it does, treat it as gap_go with leverage.
Run:  python bot.py session | check | report | status
"""
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "cc_sdk"))          # repo checkout without `pip install -e .`
sys.path.insert(0, str(HERE.parent / "gap_go_bot"))          # the signal is gap_go's own rule file, unchanged
from cc_sdk.intraday_cli import main  # noqa: E402
from cc_sdk.options_runner import SpreadSessionRunner  # noqa: E402
from cc_sdk.polygon_options import MixedFeed, polygon_from_env  # noqa: E402
from gap_go_rules import GapGoRules  # noqa: E402

from cc_sdk import BotManifest  # noqa: E402

try:
    from dotenv import load_dotenv

    load_dotenv(HERE / ".env")
except ImportError:
    pass
GAP_BPS = float(os.getenv("GAP_BPS", "70"))
WAIT_MIN = int(os.getenv("WAIT_MIN", "30"))
SYMBOLS = os.getenv("SYMBOLS", "SPY,QQQ").split(",")
DTE_MIN, DTE_MAX = int(os.getenv("DTE_MIN", "2")), int(os.getenv("DTE_MAX", "7"))
WIDTH_ATR = float(os.getenv("WIDTH_ATR", "1.0"))

MANIFEST = BotManifest(
    id="gap_go_spread", name="Gap-and-Go debit spread SPY/QQQ", version="0.1",
    strategy_line=f"gap ≥ {GAP_BPS:.0f} bp · {WAIT_MIN}-min range break · {DTE_MIN}–{DTE_MAX} DTE debit vertical, "
                  f"{WIDTH_ATR:g} ATR wide · flat at close",
    instrument="SPY,QQQ options", mode="paper",
    cadence={"session": "09:25"},
    backtest={"trades_per_year": 31,
              "source": "NOT backtested as options yet (M7.6). Signal = gap_go shares (SPX PF 1.75, 2005–2020); "
                        "the spread itself has no measured edge"},
    limits={"max_premium_usd": 5_000, "max_orders_per_day": 8, "max_position_usd": 50_000},
)


def make_runner(bot, feed, rules, symbols, **kw):
    # Underlying from Schwab; option chains from Polygon real-time (owner decision 2026-10-04).
    return SpreadSessionRunner(bot, MixedFeed(feed, polygon_from_env()), rules, symbols, dte_min=DTE_MIN,
                               dte_max=DTE_MAX, width_atr=WIDTH_ATR, **kw)


if __name__ == "__main__":
    main(MANIFEST, lambda: GapGoRules(GAP_BPS, WAIT_MIN), SYMBOLS, HERE, replay_map={"SPY": "SPX500_USD", "QQQ": "NAS100_USD"},
         make_runner=make_runner)
