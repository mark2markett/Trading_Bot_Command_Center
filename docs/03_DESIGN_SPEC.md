# Design Specification

Transcribed from the approved canvas "Trading Bot Fleet Dashboard" (3 artboards, 1440 px wide, fluid pages).
Match this. Where the canvas and this file disagree, the canvas wins.

## 1. Tokens (`cc_web/src/styles/tokens.css`)

```css
:root{
  --bg:#0E1116; --panel:#161B22; --panel-2:#1C2330; --line:#262C36;
  --fg:#E6EDF3; --fg-2:#C9D1D9; --mut:#8B949E;
  --accent:#4C8DFF; --accent-fg:#79B8FF;
  --pos:#3FB950; --neg:#F85149; --neg-fg:#FF7B72; --warn:#D29922; --warn-fg:#E3B341;
  --live-bg:#2A1215; --paper-bg:#1C2A40; --paused-bg:#262C36; --warn-bg:#2B2111; --kill-border:#5A1F1F;
  --band:#1E2A3F;
  --font:'IBM Plex Sans',system-ui,sans-serif; --mono:'IBM Plex Mono',monospace;
  --r:8px; --r-sm:6px; --gap:18px; --pad:16px;
}
```
Fonts via Google Fonts `css2` (IBM Plex Sans 400/500/600/700, IBM Plex Mono 400/500/600). Dark only in v1.
All numbers (prices, P&L, percentages, times, quantities) render in `--mono`. Labels and prose in `--font`.

## 2. Shared components

| Component | Spec |
|---|---|
| `Header` | 12/24 px padding, bottom border `--line`. Logo square 28 px in `--accent`. Nav pills: active `--panel-2` + `--fg` 600; inactive `--mut`. Right cluster: status chips (dot 8 px + 12 px text) for market, broker token, data feed; then **KILL ALL** button. |
| `KillButton` | Border `--neg`, bg `--live-bg`, text `--neg-fg` 700, power icon. Click → modal with a random 5-letter word; typing it enables Confirm. Disabled while already killed; shows "KILLED · re-arm" state instead. |
| `Tile` | `--panel`, 1 px `--line`, radius `--r`, padding 14/16. Label 12 px uppercase `--mut` letter-spacing .06em. Value 24–30 px mono 600. Optional sub-line 12 px `--mut`. Optional `LimitBar`. |
| `LimitBar` | Track 6 px `--line`, radius 3; fill colored by usage: < 60 % `--accent` or `--pos`, 60–85 % `--warn`, > 85 % `--neg`. Threshold ticks as 2 px vertical lines. |
| `ModeBadge` | 11 px mono 600, radius 4, padding 2/8. LIVE: `--live-bg`/`--neg-fg`. PAPER: `--paper-bg`/`--accent-fg`. PAUSED/KILLED: `--paused-bg`/`--mut`. |
| `StatusDot` | 9–10 px circle. running `--pos`, degraded `--warn`, paused/killed `--mut`, broken `--neg`. |
| `Panel` | `--panel` card with a 12/16 header row (h2 15 px 600 + 12 px `--mut` meta + right-aligned actions) separated by `--line`. |
| `DataTable` | 13 px, header 12 px `--mut` 500, rows separated by `--line`, cell padding 10–12/8, first/last cell 16. Body in `--mono`; name cells in `--font`. Wide tables wrap in `overflow-x:auto`. Degraded row tint `#1C1A14`. Paused rows opacity .7. |
| `AttentionItem` | Severity dot (warn/neg/accent) + bold title + 12 px `--mut` body + 11 px mono source·time. |
| `CorrelationMatrix` | CSS grid, 90 px label column + N equal columns, 3 px gap, cells padding 8, radius 3; fill by |r|: ≥.9 `--accent` with dark text, .7–.9 `#3A6BC2` white text, .3–.7 `--band`, < .3 `#1A2130`. One warning sentence beneath for any pair ≥ .7. |
| `EquityBand` | uPlot: band polygon `--band` (5–95 %), median dashed `--accent` 2 px, live solid `--fg` 2.5 px, zero line `--line`. Height 260. Legend row top-right 12 px. End label of live value. |
| `LogList` | 12 px mono, line-height 1.6, `--fg-2`; timestamps `--mut`; actions colored: queued `--warn-fg`, confirmed `--pos`, rejected `--neg-fg`. Newest first. |
| `Button` | Default: 1 px `--line`, bg `--panel-2`, `--fg` 13 px. Warn: border `--warn`, bg `--warn-bg`, text `--warn-fg` 600. Danger: border `--neg`, bg `--live-bg`, text `--neg-fg` 700. Trailing "…" means a confirm step follows. Min height 36 px; touch 44 px on phone. |

## 3. Screen 1 — Fleet overview (`/`)

Grid, max-width 1600, padding 20/24, gaps 18.

1. **Tile row** (6 columns): Portfolio equity (span 2, with 44 px sparkline, "+$X today" in `--pos`/`--neg`) · Day P&L vs limit (LimitBar, sub "Daily loss limit −2.0%") · Gross exposure (LimitBar, "Cap 1.50× equity") · Portfolio drawdown (LimitBar with ticks at pause/kill, "Pause at −6% · Kill at −10%") · Fleet health (three mono counters: running/degraded/paused).
2. **Main row** (flex-wrap): left `Bots` panel `flex: 999 1 720px`; right aside `flex: 1 1 320px`.
   - Bots panel header: title, "N configured · sorted by risk", filter pills All / Live / Paper / In position.
   - Columns: Bot (dot, name 600, strategy line 12 px) · Mode · Position · Day P&L (right) · DD (right) · Live vs backtest (✓ within band / ⚠ metric vs expected / ✗ reason) · Heartbeat (HH:MM ✓, or "missed 23 min" in `--neg-fg`) · Open →.
   - Aside: `Needs attention` panel with count pill; `Strategy correlation · 60d` panel.
3. **Bottom row** (3 columns): Today's schedule (time · ✓/○ · text) · Open orders (mono, right-aligned type/purpose, "reconciled against Schwab HH:MM") · Recent fills (date · side qty type · price + slip colored; footer: avg slippage vs assumption).

Interactions: row click → `/bots/:id`. KILL ALL → confirm modal. Filter pills are client-side. Auto-refresh 15 s; a "stale" badge appears if the last successful fetch is > 60 s old.

## 4. Screen 2 — Bot detail (`/bots/:id`)

1. **Header**: ‹ Fleet breadcrumb · status dot · name h1 18 px · ModeBadge · version + rule summary 12 px `--mut` · actions right: Re-check signal, Pause after exit, Flatten now… (warn), Kill bot… (danger).
2. **Tile row** (4): Position (LONG qty · n/10 bars, or FLAT + last trade line) · Signal now (grid of indicator → value, with a 6 px rail showing current value vs trigger tick; sub-line in words: "needs two sharp down closes") · Allocated equity (caps, account last-4 masked) · Health (4 rows: heartbeat, data feed, broker = state, next run).
3. **Main row**: left `Live vs backtest expectation` panel (EquityBand + 5 mini stats: trades, win rate, avg win/loss, slippage/fill, parity verdict, each "live / backtest"); right column: `Risk limits · this bot` (LimitBars for max position, bot drawdown, consecutive losses, orders today; text rows for price collar and stale-data guard) and `Parameters` (key → mono value; footer sentence about versioning + link to history).
4. **Bottom row**: left `Trades` table (Entry, Exit, Qty, In → Out, Bars, Reason, P&L, Slip; Export CSV); right `Decision log` (LogList).

Signal rail rule: left tick at trigger (e.g. RSI 10), marker at current value, both on a 0–100 scale for RSI; for price-vs-SMA show distance in % instead.

## 5. Screen 3 — Risk & controls (`/risk`)

1. **Header**: breadcrumb, h1, one sentence: "Limits are enforced in code before any order leaves the machine. This page shows them; it does not bypass them." Right: last limit change + audit link.
2. **Top row** (2 panels): `Kill switch` panel with red border `--kill-border` and bg `#1A1215`: title in `--neg-fg`, "armed · last test DATE ✓", explanatory sentence, three buttons (KILL ALL danger · Flatten all keep bots warn · Pause new entries default), footnote "Risk-reducing orders are never blocked by a pause." · `Drawdown ladder · portfolio` panel: current DD bar with ticks at −6/−8/−10, then three rows threshold → action; footer "Measured on broker liquidation value…".
3. **Bottom row** (2 columns): left `Pre-trade checks · every order` table (Check · Limit · Today's peak · On breach) with "all passing" / "N failing" in header; right column: `Heartbeats & dependencies` (2-col grid of name → status) and `Control audit log` (LogList).

Editing a limit: click value → inline input → Save asks for a one-line note → writes `controls` row → UI shows before → after in the audit log.

## 6. Phone (≤ 480 px)

- Header wraps; nav becomes a bottom tab bar (Fleet, Bots, Risk, Alerts); KILL ALL stays in the top bar, full width red.
- Tiles stack 2-up then 1-up. Bot table collapses to cards: name + mode, position, day P&L, verdict, heartbeat.
- Correlation matrix hides below 480 px; the warning sentence stays.
- All buttons ≥ 44 px tall.

## 7. Copy rules

Plain language. No "leverage synergies". Verdicts are sentences a trader would say: "win rate 58% vs 73%", "edge decayed 2025", "needs two sharp down closes". Never hide a bad number behind a neutral color.
