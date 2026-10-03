# SPY Daily Mean Reversion Bot (Schwab)

Runs the strategy validated in TradingView (1993–2026: 77% winners, profit factor 2.28, max drawdown 11.6%).

**Rules**
- Buy SPY at the close when RSI(2) < 10 and close > 200-day SMA.
- Sell at the close when close > 5-day SMA, or after 10 trading days.
- Protective stop 5% below entry (resting GTC stop order).
- One position, 100% of equity (configurable), long only, no leverage.

## Read this first: Schwab has no paper account via API

Schwab's `paperMoney` lives inside thinkorswim only. Every order sent through the Schwab API is **real**.
So this bot's `MODE=paper` does not touch Schwab's order endpoint at all. It computes the real signal on real
data, then simulates the fill at the actual closing price and keeps a ledger in `paper_ledger.json`.
That is the only safe way to paper trade this strategy with Schwab. `MODE=live` is locked behind an explicit
`LIVE_CONFIRM` flag.

## Setup (Windows, Python 3.11+)

```powershell
cd C:\path\to\spy_mr_bot
python -m venv .venv ; .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

Edit `.env`. For paper mode you can leave the Schwab keys blank; the bot then uses free end-of-day data from
Stooq (fine for a 3:50pm decision, since Stooq's last bar is yesterday and the bot asks for the live price —
without Schwab it falls back to yesterday's close, so **add Schwab keys for accurate 3:50pm signals**).

### Schwab API keys (needed for live, recommended for paper)
1. Go to developer.schwab.com, create an app, product "Accounts and Trading Production", callback URL
   `https://127.0.0.1:8182`. Approval takes a few days ("Ready for use").
2. Put the App Key / Secret in `.env`. Then run once, interactively:
   ```powershell
   python bot.py auth
   ```
   A browser opens, you log in to Schwab, approve, and the token is saved to `schwab_token.json`.
   The token refreshes itself; you must re-run `auth` about every 7 days (Schwab's refresh-token limit).
   **Never share or commit `schwab_token.json` or `.env`.**

## Running

```powershell
python bot.py check       # print today's signal, change nothing
python bot.py decide      # 3:50pm ET: queue MOC order if the rules fire
python bot.py reconcile   # 9:45am ET: confirm fills, place the 5% stop, update state
python bot.py status      # show equity, position, state
```

Install the two daily scheduled tasks (3:50pm and 9:45am local time):
```powershell
.\install_tasks.ps1
```
The PC must be on and awake at those times (tasks are set to wake it).

## Going live (only after 3–4 paper signals match the backtest)

1. In `.env`: `MODE=live` and `LIVE_CONFIRM=I_UNDERSTAND_THIS_IS_REAL_MONEY`.
2. Set `MAX_SHARES` to a small cap for the first live trade.
3. `python bot.py status` must show the correct account and equity before the next 3:50pm run.

State is kept per mode (`state_paper.json`, `state_live.json`), so switching does not carry a paper position over.

## Files
- `strategy.py` – pure signal logic (RSI(2) Wilder, SMAs, entry/exit/stop). Unit-tested against pandas.
- `broker.py` – `SchwabBroker` (live) and `PaperBroker` (simulated fills on real closes).
- `bot.py` – scheduler entry point and state machine.
- `tests/` – 5 tests: RSI parity, rules, full lifecycle, crash-stop path. Run `python -m pytest -q tests`.
- `bot.log` – every run, every decision, every order.

## Known limits
- The 3:50pm signal uses the live price as a provisional close. On a day where SPY moves sharply in the last
  10 minutes, the backtest and the bot can disagree. Over 33 years of signals this is a small effect, but it's
  not zero.
- Market holidays: the bot runs, sees no new bar, and does nothing. Early-close days (1pm) are **not** handled;
  on those days (day after Thanksgiving, Christmas Eve, July 3) run `python bot.py decide` manually at 12:50pm.
- Schwab tokens expire weekly. If `reconcile` logs an auth error, run `python bot.py auth` again.
- This is a backtest-derived system, not a forecast. Size it so a 12% drawdown is survivable.
