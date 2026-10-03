// Typed client over /api. Shapes mirror cc_server/api.py; kept hand-written and small on purpose.
export type Verdict = 'within' | 'drift' | 'n/a'
export type Status = 'running' | 'degraded' | 'paused' | 'killed'

export interface Position { bot_id: string; symbol: string; qty: number; avg_price: number | null; entry_at: string | null; bars_held: number; updated_at: string }
export interface Heartbeat { bot_id: string; run: string; at: string; ok: number; detail: string }
export interface BotSummary {
  id: string; name: string; strategy_line: string; mode: 'paper' | 'live'; version: string; instrument: string; status: Status
  cadence: Record<string, string>; position: Position | null; day_pnl: number; drawdown: number; equity: number | null
  parity: { verdict: Verdict; sentence: string }; heartbeat: Heartbeat | null
  flags: { killed: boolean; paused: boolean; flatten: boolean }; rejected_24h: number
}
export interface Alert { id: number; at: string; severity: 'page' | 'digest' | 'info'; bot_id: string | null; bot_name: string | null; kind: string; message: string; acknowledged_at: string | null }
export interface Fill { id: number; at: string; qty: number; price: number; expected_price: number; slippage: number; side: string | null; type: string | null; symbol: string | null; bot_name: string | null }
export interface Order { id: number; at: string; side: string; qty: number; type: string; stop_price: number | null; limit_price: number | null; symbol: string; bot_name: string; reason: string }
export interface Fleet {
  as_of: string; equity: number | null; equity_series: [string, number][]; day: { pnl: number; pct: number }; daily_loss_limit_pct: number
  exposure: { usd: number; ratio: number; cap: number }
  drawdown: { dd: number; equity: number | null; peak: number | null; pause: number; flatten: number; kill: number }
  counts: Record<string, number>; bots: BotSummary[]; attention: Alert[]
  correlation: { ids: string[]; matrix: Record<string, Record<string, number>>; flags: string[] }
  schedule: { time: string; bot: string; run: string; done: boolean }[]; open_orders: Order[]; fills: Fill[]
  market_open: boolean; killed: boolean; entries_paused: boolean; token: { present: boolean; days_left: number | null }; next_early_close: string
}
export interface Trade { id: number; entry_at: string; exit_at: string; qty: number; entry_px: number; exit_px: number; bars: number; exit_reason: string; pnl: number; slippage: number }
export interface Decision { id: number; at: string; run: string; signal: Record<string, unknown>; action: string; reason: string }
export interface BotDetail extends BotSummary {
  backtest: Record<string, number>; limits: Record<string, number>
  parity_detail: { trades: number; live: Record<string, number>; flags: string[]; verdict: Verdict; sentence: string; win_rate_band?: [number, number] }
  equity_series: [string, number][]; expected: { median: number[]; lo: number[]; hi: number[] }
  trades: Trade[]; fills: Fill[]; decisions: Decision[]; usage: { orders_today: number; consecutive_losses: number }; stop_price: number | null
}
export interface Control { id: number; at: string; actor: string; action: string; target: string; before: unknown; after: unknown; note: string }
export interface Risk {
  killed: boolean; entries_paused: boolean; kill_flag: Record<string, string> | null
  drawdown: { dd: number; equity: number | null; peak: number | null }; limits: Record<string, number>; exposure: { usd: number; ratio: number; cap: number }
  checks: { check: string; limit: string; peak: string; on_breach: string }[]
  dependencies: { riskd_last: { at: string } | null; token: { present: boolean; days_left: number | null }; calendar_loaded: boolean; host: { disk_free_gb: number }; alert_test: Record<string, string> | null; bots: number }
  audit: Control[]; last_drill: Control | null
}

async function j<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, { ...init, headers: { 'content-type': 'application/json', ...(init?.headers || {}) } })
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`)
  return r.json() as Promise<T>
}

export const api = {
  fleet: () => j<Fleet>('/api/fleet'),
  bot: (id: string) => j<BotDetail>(`/api/bots/${id}`),
  risk: () => j<Risk>('/api/risk'),
  alerts: () => j<Alert[]>('/api/alerts'),
  ack: (id: number) => j('/api/alerts/' + id + '/ack', { method: 'POST' }),
  alertTest: () => j<Record<string, string>>('/api/alerts/test', { method: 'POST' }),
  confirmWord: (action: string) => j<{ word: string }>(`/api/controls/confirm/${encodeURIComponent(action)}`, { method: 'POST' }),
  control: (path: string, body: { word?: string; note?: string }) => j(`/api/controls/${path}`, { method: 'POST', body: JSON.stringify(body) }),
  setLimit: (scope: string, key: string, value: number, note: string) => j(`/api/limits/${scope}/${key}`, { method: 'PUT', body: JSON.stringify({ value, note }) }),
}
