const ET = 'America/New_York'

export const money = (v: number | null | undefined, digits = 0) =>
  v == null ? '—' : (v < 0 ? '−' : '') + '$' + Math.abs(v).toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits })
export const signedMoney = (v: number | null | undefined) => (v == null ? '—' : (v >= 0 ? '+' : '−') + '$' + Math.abs(v).toLocaleString('en-US', { maximumFractionDigits: 0 }))
export const pct = (v: number | null | undefined, digits = 1, signed = false) =>
  v == null ? '—' : (signed && v > 0 ? '+' : v < 0 ? '−' : '') + (Math.abs(v) * 100).toFixed(digits) + '%'
export const px = (v: number | null | undefined) => (v == null ? '—' : v.toFixed(2))
export const cents = (v: number | null | undefined) => (v == null ? '—' : (v >= 0 ? '+' : '−') + (Math.abs(v) * 100).toFixed(1) + '¢')
export const timeET = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleTimeString('en-US', { timeZone: ET, hour: '2-digit', minute: '2-digit', hour12: false }) : '—'
export const dateET = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleDateString('en-US', { timeZone: ET, month: '2-digit', day: '2-digit' }) : '—'
export const dtET = (iso: string | null | undefined) => (iso ? `${dateET(iso)} ${timeET(iso)}` : '—')
export const agoMin = (iso: string | null | undefined) => (iso ? Math.round((Date.now() - new Date(iso).getTime()) / 60000) : null)
export const tone = (v: number) => (v > 0 ? 'pos' : v < 0 ? 'neg' : 'mut')
export const usageTone = (ratio: number) => (ratio > 0.85 ? 'var(--neg)' : ratio > 0.6 ? 'var(--warn)' : 'var(--accent)')

// ---- options (M7.4) ----
const OCC = /^[A-Z.]{1,6} *\d{6}[CP]\d{8}$/
/** True for an OCC option symbol (positions store option legs by OCC symbol, price per share). */
export const isOcc = (symbol: string | null | undefined) => OCC.test(symbol ?? '')
/** 100 for an option contract, 1 for shares. */
export const contractMultiplier = (symbol: string | null | undefined) => (isOcc(symbol) ? 100 : 1)

export interface SpreadLive {
  underlying: string; right: 'C' | 'P'; expiry: string; qty: number; legs: string[]; strikes: number[]; dte: number
  delta_shares: number; theta_usd_day: number; value_usd: number; cost_usd: number; unrealized_usd: number; updated_at: string
}
const signedInt = (v: number) => (v >= 0 ? '+' : '−') + Math.abs(Math.round(v)).toLocaleString('en-US')
/** One plain line a trader would say: "SPY call spread 570/575 ×19 · Δ +380 sh · θ −$13/day · 2 DTE". */
export const spreadLine = (o: SpreadLive) =>
  `${o.underlying} ${o.right === 'C' ? 'call' : 'put'} spread ${o.strikes.map(k => (Number.isInteger(k) ? k : k.toFixed(1))).join('/')} ×${o.qty}` +
  ` · Δ ${signedInt(o.delta_shares)} sh · θ ${signedMoney(o.theta_usd_day)}/day · ${o.dte} DTE`
