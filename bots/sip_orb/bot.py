"""Stocks-in-Play ORB paper bot. Universe from the M2M scanner at 09:35 (SCANNER_URL), rules in sip_orb_rules.py.
Published: Sharpe 2.81, 17% win rate (Zarattini/Barbon/Aziz 2024); QuantConnect replication ≈ 2.4 for 2016. Not
reproducible on index data (see docs/RESEARCH_RESULTS.md) — paper evidence only.
Run:  python bot.py session | status      (replay needs single-stock minute data; not available offline)"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cc_sdk"))  # repo checkout without `pip install -e .`
from cc_sdk.intraday_cli import main
from sip_orb_rules import SipOrbRules
from sip_scanner import universe

from cc_sdk import BotManifest  # noqa: E402

HERE = Path(__file__).resolve().parent
try:
    from dotenv import load_dotenv

    load_dotenv(HERE / ".env")
except ImportError:
    pass
TOP_N = int(os.getenv("TOP_N", "20"))

MANIFEST = BotManifest(
    id="sip_orb", name="Stocks-in-Play ORB", version="0.1",
    strategy_line="top-20 relative-volume stocks at 09:35 · 5-min ORB in first-candle direction · stop 10% ATR · flat at close",
    instrument="scanner", mode="paper", cadence={"session": "09:25"},
    backtest={"win_rate": 0.17, "profit_factor": 1.4, "avg_win": 0.03, "avg_loss": -0.004, "trades_per_year": 2500,
              "slippage_assumed": 0.0005, "max_dd": 0.15, "source": "Zarattini/Barbon/Aziz 2024 (published, not replicated here)"},
    limits={"max_position_usd": 10_000, "max_orders_per_day": 60, "max_order_qty": 5_000},
)

if __name__ == "__main__":
    import sys

    from cc_sdk.intraday import SessionRunner

    from cc_sdk import Bot

    if len(sys.argv) > 1 and sys.argv[1] == "session":
        from cc_sdk.schwab_feed import SchwabFeed

        try:  # .env.local holds CC_TOKEN_BROKER_URL / CC_TOKEN_BROKER_SECRET (this branch bypasses intraday_cli.main)
            from dotenv import load_dotenv

            load_dotenv(HERE / ".env.local", override=True)
        except ImportError:
            pass
        bot = Bot(MANIFEST)
        with bot.run("session"):
            SessionRunner(bot, SchwabFeed.from_broker(HERE), SipOrbRules(), [], risk_pct=0.01,
                          universe_fn=lambda now: universe(now, TOP_N)).loop()
    else:
        main(MANIFEST, SipOrbRules, [], HERE, replay_map={})
