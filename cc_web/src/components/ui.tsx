import { useEffect, useState, type ReactNode } from 'react'
import { NavLink } from 'react-router-dom'
import { api } from '../lib/api'
import { usageTone } from '../lib/format'

export function Dot({ tone, lg }: { tone: 'pos' | 'warn' | 'neg' | 'mut' | 'acc'; lg?: boolean }) {
  return <span className={`dot ${tone} ${lg ? 'lg' : ''}`} aria-hidden="true" />
}

export const statusTone = (s: string): 'pos' | 'warn' | 'neg' | 'mut' =>
  s === 'running' ? 'pos' : s === 'degraded' ? 'warn' : s === 'broken' ? 'neg' : 'mut'

export function ModeBadge({ mode, status }: { mode: string; status?: string }) {
  if (status === 'killed' || status === 'paused') return <span className={`badge ${status}`}>{status.toUpperCase()}</span>
  return <span className={`badge ${mode}`}>{mode.toUpperCase()}</span>
}

export function Tile({ label, value, sub, children, span2, cls }: { label: string; value?: ReactNode; sub?: ReactNode; children?: ReactNode; span2?: boolean; cls?: string }) {
  return (
    <div className={`tile ${span2 ? 'span2' : ''}`}>
      <div className="lbl">{label}</div>
      {value !== undefined && <div className={`big ${cls || ''}`}>{value}</div>}
      {children}
      {sub && <div className="sub">{sub}</div>}
    </div>
  )
}

export function LimitBar({ ratio, ticks, color, thin }: { ratio: number; ticks?: { at: number; color: string }[]; color?: string; thin?: boolean }) {
  const r = Math.max(0, Math.min(1, ratio))
  return (
    <div className={`bar ${thin ? 'thin' : ''}`} role="meter" aria-valuenow={Math.round(r * 100)} aria-valuemin={0} aria-valuemax={100}>
      <b style={{ width: `${r * 100}%`, background: color || usageTone(r) }} />
      {ticks?.map((t, i) => <i key={i} style={{ left: `${t.at * 100}%`, background: t.color }} />)}
    </div>
  )
}

export function Panel({ title, meta, right, children, flat }: { title: string; meta?: ReactNode; right?: ReactNode; children: ReactNode; flat?: boolean }) {
  if (flat) return <div className="panel flat"><h2>{title}</h2>{children}</div>
  return (
    <div className="panel">
      <div className="ph"><h2>{title}</h2>{meta && <span className="meta">{meta}</span>}{right && <div className="right">{right}</div>}</div>
      {children}
    </div>
  )
}

export function Sparkline({ series, color = 'var(--pos)' }: { series: number[]; color?: string }) {
  if (series.length < 2) return <svg width="100%" height="44" aria-hidden="true" />
  const min = Math.min(...series), max = Math.max(...series), rng = max - min || 1
  const pts = series.map((v, i) => `${(i / (series.length - 1)) * 320},${40 - ((v - min) / rng) * 36 + 2}`).join(' ')
  return <svg viewBox="0 0 320 44" width="100%" height="44" style={{ marginTop: 8, display: 'block' }} aria-hidden="true"><polyline fill="none" stroke={color} strokeWidth="2" points={pts} /></svg>
}

/** Two-step destructive action: fetch a word, operator types it, then confirm. */
export function ConfirmModal({ action, title, body, onDone, onClose, cls }: { action: string; title: string; body: string; onDone: () => void; onClose: () => void; cls?: string }) {
  const [word, setWord] = useState<string | null>(null)
  const [typed, setTyped] = useState('')
  const [note, setNote] = useState('')
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => { api.confirmWord(action).then(r => setWord(r.word)).catch(e => setErr(String(e))) }, [action])
  const path = action.includes(':') ? `bot/${action.split(':')[1]}/${action.split(':')[0]}` : action
  const go = async () => {
    try { await api.control(path, { word: typed, note }); onDone() } catch (e) { setErr(String(e)) }
  }
  return (
    <div className="modal-bg" role="dialog" aria-modal="true" aria-labelledby="cm-title">
      <div className="modal">
        <h2 id="cm-title" className="neg">{title}</h2>
        <p style={{ margin: 0, color: 'var(--fg-2)' }}>{body}</p>
        <label>Type <b className="mono">{word ?? '…'}</b> to confirm<br />
          <input autoFocus value={typed} onChange={e => setTyped(e.target.value)} aria-label="confirmation word" style={{ width: '100%', marginTop: 6 }} /></label>
        <label>Note (goes in the audit log)<br /><input value={note} onChange={e => setNote(e.target.value)} style={{ width: '100%', marginTop: 6 }} /></label>
        {err && <div className="neg" style={{ fontSize: 12 }}>{err}</div>}
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <button className="btn" onClick={onClose}>Cancel</button>
          <button className={`btn ${cls || 'danger'}`} disabled={!word || typed !== word} onClick={go}>Confirm</button>
        </div>
      </div>
    </div>
  )
}

export function Header({ fleet, stale }: { fleet?: { market_open: boolean; token: { present: boolean; days_left: number | null }; killed: boolean; as_of: string } | null; stale: boolean }) {
  const [kill, setKill] = useState(false)
  const tokenTone = !fleet?.token.present ? 'mut' : (fleet.token.days_left ?? 0) < 2 ? 'neg' : (fleet.token.days_left ?? 0) < 4 ? 'warn' : 'pos'
  return (
    <>
      <header className="hdr">
        <div className="logo"><i><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#0E1116" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><polyline points="3 17 9 11 13 15 21 7" /><polyline points="14 7 21 7 21 14" /></svg></i>Control Plane</div>
        <nav className="nav">
          <NavLink to="/" end className={({ isActive }) => (isActive ? 'on' : '')}>Fleet</NavLink>
          <NavLink to="/bots" className={({ isActive }) => (isActive ? 'on' : '')}>Bots</NavLink>
          <NavLink to="/risk" className={({ isActive }) => (isActive ? 'on' : '')}>Risk</NavLink>
          <NavLink to="/journal" className={({ isActive }) => (isActive ? 'on' : '')}>Journal</NavLink>
          <NavLink to="/research" className={({ isActive }) => (isActive ? 'on' : '')}>Research</NavLink>
        </nav>
        <div className="chips">
          {stale && <span className="stale">stale · last update failed</span>}
          <span className="chip"><Dot tone={fleet?.market_open ? 'pos' : 'mut'} />{fleet?.market_open ? 'Market open' : 'Market closed'}</span>
          <span className="chip"><Dot tone={tokenTone} />{fleet?.token.present ? `Schwab · token ${fleet.token.days_left?.toFixed(0)}d left` : 'Schwab · not connected'}</span>
          <span className="killwrap">
            {fleet?.killed
              ? <button className="btn danger" onClick={() => setKill(true)}>KILLED · re-arm…</button>
              : <button className="btn danger" onClick={() => setKill(true)} aria-label="Kill all bots"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><path d="M18.36 6.64a9 9 0 1 1-12.73 0" /><line x1="12" y1="2" x2="12" y2="12" /></svg>KILL ALL</button>}
          </span>
        </div>
      </header>
      {fleet?.killed && <div className="killbanner">Kill switch is active. All bots disabled, positions being flattened. Re-arm from the header or the Risk page when you have checked the account.</div>}
      {kill && (fleet?.killed
        ? <ConfirmModal action="rearm" title="Re-arm the fleet" body="Removes the kill flag and fleet pause. Bots resume on their next scheduled run. Confirm you have checked the account first." cls="warn" onDone={() => { setKill(false); location.reload() }} onClose={() => setKill(false)} />
        : <ConfirmModal action="kill_all" title="Kill all bots" body="Cancels open orders, flattens every position at market on each bot's next run, disables all bots, and blocks new orders until re-armed by a person." onDone={() => { setKill(false); location.reload() }} onClose={() => setKill(false)} />)}
      <nav className="tabs" aria-label="Sections">
        <NavLink to="/" end className={({ isActive }) => (isActive ? 'on' : '')}>Fleet</NavLink>
        <NavLink to="/bots" className={({ isActive }) => (isActive ? 'on' : '')}>Bots</NavLink>
        <NavLink to="/risk" className={({ isActive }) => (isActive ? 'on' : '')}>Risk</NavLink>
        <NavLink to="/journal" className={({ isActive }) => (isActive ? 'on' : '')}>Alerts</NavLink>
      </nav>
    </>
  )
}
