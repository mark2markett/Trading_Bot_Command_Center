PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS bots(
  id TEXT PRIMARY KEY, name TEXT NOT NULL, strategy_line TEXT, mode TEXT CHECK(mode IN('paper','live')) NOT NULL,
  version TEXT, instrument TEXT, cadence_json TEXT, backtest_json TEXT, limits_json TEXT,
  status TEXT DEFAULT 'running', created_at TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS heartbeats(id INTEGER PRIMARY KEY, bot_id TEXT, run TEXT, at TEXT, ok INTEGER, detail TEXT);
CREATE INDEX IF NOT EXISTS ix_hb ON heartbeats(bot_id, at);
CREATE TABLE IF NOT EXISTS decisions(id INTEGER PRIMARY KEY, bot_id TEXT, at TEXT, run TEXT, signal_json TEXT, action TEXT, reason TEXT);
CREATE INDEX IF NOT EXISTS ix_dec ON decisions(bot_id, at);
CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY, bot_id TEXT, at TEXT, broker_order_id TEXT, side TEXT, qty INTEGER,
  type TEXT, limit_price REAL, stop_price REAL, status TEXT, reason TEXT, risk_result_json TEXT, symbol TEXT, ref_price REAL);
CREATE INDEX IF NOT EXISTS ix_ord ON orders(bot_id, at);
CREATE TABLE IF NOT EXISTS fills(id INTEGER PRIMARY KEY, order_id INTEGER, bot_id TEXT, at TEXT, qty INTEGER, price REAL,
  expected_price REAL, slippage REAL, commission REAL);
CREATE TABLE IF NOT EXISTS positions(bot_id TEXT, symbol TEXT, qty INTEGER, avg_price REAL, entry_at TEXT,
  bars_held INTEGER, updated_at TEXT, stop_price REAL, side TEXT, PRIMARY KEY(bot_id, symbol));
CREATE TABLE IF NOT EXISTS equity(id INTEGER PRIMARY KEY, bot_id TEXT, at TEXT, equity REAL, source TEXT CHECK(source IN('bot','broker')));
CREATE INDEX IF NOT EXISTS ix_eq ON equity(bot_id, at);
CREATE TABLE IF NOT EXISTS trades(id INTEGER PRIMARY KEY, bot_id TEXT, entry_at TEXT, exit_at TEXT, qty INTEGER, entry_px REAL,
  exit_px REAL, bars INTEGER, exit_reason TEXT, pnl REAL, slippage REAL);
CREATE INDEX IF NOT EXISTS ix_tr ON trades(bot_id, exit_at);
CREATE TABLE IF NOT EXISTS alerts(id INTEGER PRIMARY KEY, at TEXT, severity TEXT CHECK(severity IN('page','digest','info')),
  bot_id TEXT, kind TEXT, message TEXT, acknowledged_at TEXT, delivered_at TEXT);
CREATE TABLE IF NOT EXISTS controls(id INTEGER PRIMARY KEY, at TEXT, actor TEXT, action TEXT, target TEXT, before_json TEXT,
  after_json TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS limits(scope TEXT, key TEXT, value_json TEXT, updated_at TEXT, PRIMARY KEY(scope, key));
CREATE TABLE IF NOT EXISTS journal(id INTEGER PRIMARY KEY, trade_id INTEGER, at TEXT, tags TEXT, note TEXT, attachment_path TEXT);
CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, value_json TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS option_trades(id INTEGER PRIMARY KEY, trade_id INTEGER, bot_id TEXT, underlying TEXT, expiry TEXT,
  right TEXT, legs_json TEXT, qty INTEGER, net_debit REAL, net_credit REAL, und_entry REAL, und_exit REAL, net_delta REAL,
  spread_pnl REAL, share_equiv_pnl REAL, close_method TEXT, at TEXT);
CREATE INDEX IF NOT EXISTS ix_opt ON option_trades(bot_id, at);
CREATE TABLE IF NOT EXISTS paper_marks(symbol TEXT PRIMARY KEY, price REAL NOT NULL, at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS paper_equity(id INTEGER PRIMARY KEY, at TEXT NOT NULL, equity REAL NOT NULL);
CREATE INDEX IF NOT EXISTS ix_paper_equity_at ON paper_equity(at);
