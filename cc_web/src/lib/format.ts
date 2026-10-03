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
