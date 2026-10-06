import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api, type Risk } from '../lib/api'
import { dateET, dtET, money } from '../lib/format'
import { ConfirmModal, Panel } from '../components/ui'

export function RiskPage() {
  const q = useQuery({ queryKey: ['risk'], queryFn: api.risk, refetchInterval: 15000 })
  const [modal, setModal] = useState<null | 'kill_all' | 'flatten_all' | 'rearm'>(null)
  const [edit, setEdit] = useState<{ key: string; value: string; note: string } | null>(null)
  const [testing, setTesting] = useState<string | null>(null)
  if (q.isLoading || !q.data) return <main><div className="empty">Loading…</div></main>
  const r: Risk = q.data
  const lim = r.limits
  const dd = r.drawdown.dd
  const pauseEntries = async () => { await api.control('pause_entries', { note: 'manual' }); q.refetch() }
  const resumeEntries = async () => { await api.control('resume_entries', { note: 'manual' }); q.refetch() }
  const saveLimit = async () => {
    if (!edit) return
    await api.setLimit('portfolio', edit.key, parseFloat(edit.value), edit.note); setEdit(null); q.refetch()
  }
  const limitRow = (key: string, label: string, fmt: (v: number) => string) => (
    <div style={{ display: 'grid', gridTemplateColumns: '70px 1fr auto', gap: 10, alignItems: 'center' }}>
      <span className="mono warn">{fmt(lim[key])}</span><span>{label}</span>
      <button className="btn sm ghost" onClick={() => setEdit({ key, value: String(lim[key]), note: '' })} aria-label={`edit ${key}`}>edit</button>
    </div>
  )
  return (
    <main>
      <header className="hdr" style={{ padding: 0, border: 0 }}>
        <Link to="/" className="chip">‹ Fleet</Link><span className="mut">/</span>
        <h1 style={{ fontSize: 18, fontWeight: 700 }}>Risk &amp; controls</h1>
        <span className="mut" style={{ fontSize: 12 }}>Limits are enforced in code before any order leaves the machine. This page shows them; it does not bypass them.</span>
        <span className="mut" style={{ marginLeft: 'auto', fontSize: 12 }}>{r.audit[0] ? `Last change ${dateET(r.audit[0].at)} by ${r.audit[0].actor}` : 'No changes yet'} · <a href="#audit">audit log</a></span>
      </header>

      <section className="row stretch">
        <div className="panel" style={{ flex: '1 1 420px', minWidth: 0, background: 'var(--kill-bg)', borderColor: 'var(--kill-border)', padding: '16px 18px', display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#FF7B72" strokeWidth="2.5" strokeLinecap="round" aria-hidden="true"><path d="M18.36 6.64a9 9 0 1 1-12.73 0" /><line x1="12" y1="2" x2="12" y2="12" /></svg>
            <h2 className="neg" style={{ fontSize: 16, fontWeight: 700 }}>Kill switch</h2>
            <span className="mut" style={{ marginLeft: 'auto', fontSize: 12 }}>{r.killed ? <span className="neg">FIRED · {r.kill_flag?.reason}</span> : 'armed'}{r.last_drill ? ` · last drill ${dateET(r.last_drill.at)} ✓` : ' · no drill recorded'}</span>
          </div>
          <p style={{ margin: 0, fontSize: 13, color: 'var(--fg-2)' }}>Cancels every open order, flattens every position at market on each bot's next run, disables all bots, and blocks new orders until re-armed by a person. Two-step: press, then type the word shown.</p>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,minmax(0,1fr))', gap: 8 }}>
            {r.killed ? <button className="btn warn" onClick={() => setModal('rearm')}>Re-arm…</button> : <button className="btn danger" onClick={() => setModal('kill_all')}>KILL ALL</button>}
            <button className="btn warn" onClick={() => setModal('flatten_all')}>Flatten all, keep bots</button>
            {r.entries_paused ? <button className="btn" onClick={resumeEntries}>Resume new entries</button> : <button className="btn" onClick={pauseEntries}>Pause new entries</button>}
          </div>
          <div className="mut" style={{ fontSize: 12 }}>Risk-reducing orders (stops, closes) are never blocked by a pause. Matches FIA guidance.</div>
        </div>

        <div className="panel" style={{ flex: '1 1 420px', minWidth: 0, padding: '16px 18px' }}>
          <h2 style={{ fontSize: 15, fontWeight: 600, marginBottom: 10 }}>Drawdown ladder · portfolio</h2>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, fontSize: 13 }}>
            <div style={{ display: 'grid', gridTemplateColumns: '70px 1fr auto', gap: 10, alignItems: 'center' }}>
              <span className={`mono ${dd >= lim.dd_pause_pct ? 'neg' : 'pos'}`}>{r.drawdown.equity == null ? 'unavailable' : `now −${(dd * 100).toFixed(1)}%`}</span>
              <div className="bar" style={{ marginTop: 0, height: 8 }}><b style={{ width: `${Math.min(100, (dd / lim.dd_kill_pct) * 100)}%`, background: dd >= lim.dd_pause_pct ? 'var(--neg)' : 'var(--pos)' }} />
                <i style={{ left: `${(lim.dd_pause_pct / lim.dd_kill_pct) * 100}%`, background: 'var(--warn)' }} /><i style={{ left: `${(lim.dd_flatten_pct / lim.dd_kill_pct) * 100}%`, background: 'var(--neg)' }} /></div>
              <span className="mut">of −{(lim.dd_kill_pct * 100).toFixed(0)}%</span>
            </div>
            {limitRow('dd_pause_pct', 'Pause new entries fleet-wide. Open positions keep their exits.', v => `−${(v * 100).toFixed(0)}%`)}
            {limitRow('dd_flatten_pct', 'Flatten the two most correlated bots.', v => `−${(v * 100).toFixed(0)}%`)}
            {limitRow('dd_kill_pct', 'Kill switch fires automatically. Requires manual re-arm.', v => `−${(v * 100).toFixed(0)}%`)}
            {limitRow('daily_loss_limit_pct', 'Daily loss limit (shown on the Fleet tile).', v => `−${(v * 100).toFixed(1)}%`)}
            {limitRow('max_gross_exposure', 'Max gross exposure as a multiple of equity.', v => `${v.toFixed(2)}×`)}
          </div>
          <div className="mut" style={{ marginTop: 12, paddingTop: 10, borderTop: '1px solid var(--line)', fontSize: 12 }}>Measured on {r.drawdown.source === 'paper' ? 'the shared paper account: starting capital plus realized and freshly marked unrealized P&L' : 'broker liquidation value'} ({r.drawdown.equity ? money(r.drawdown.equity) : 'none recorded yet'}). Per-bot starting balances are never added together. Missing or stale account valuation blocks new entries.</div>
        </div>
      </section>

      <section className="grid2">
        <Panel title="Pre-trade checks · every order" right={<span className="pos" style={{ fontSize: 12 }}>enforced in cc_sdk</span>}>
          <div className="scroll"><table>
            <thead><tr><th>Check</th><th>Limit</th><th>Today's peak</th><th>On breach</th></tr></thead>
            <tbody>{r.checks.map(c => <tr key={c.check}><td className="sans">{c.check}</td><td>{c.limit}</td><td>{c.peak}</td><td className="sans mut">{c.on_breach}</td></tr>)}</tbody>
          </table></div>
        </Panel>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--gap)' }}>
          <Panel title="Heartbeats & dependencies" flat>
            <div className="grid2" style={{ gap: 8, fontSize: 13 }}>
              <Dep name="riskd loop" ok={!!r.dependencies.riskd_last} val={r.dependencies.riskd_last ? `✓ ${dtET(r.dependencies.riskd_last.at)}` : '✗ not running'} />
              <Dep name="Schwab token" ok={r.dependencies.token.present && (r.dependencies.token.days_left ?? 0) >= 2} warn={r.dependencies.token.present && (r.dependencies.token.days_left ?? 0) < 4} val={r.dependencies.token.present ? `${r.dependencies.token.days_left?.toFixed(1)} days` : 'not connected'} />
              <Dep name="Market calendar" ok={r.dependencies.calendar_loaded} val="✓ 2025–2027 loaded" />
              <Dep name="Host disk" ok={r.dependencies.host.disk_free_gb > 2} val={`✓ ${r.dependencies.host.disk_free_gb} GB free`} />
              <Dep name="Bots registered" ok={r.dependencies.bots > 0} val={String(r.dependencies.bots)} />
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, padding: '8px 10px', background: 'var(--bg)', borderRadius: 6 }}>
                <span>Alert channel</span>
                <button className="btn sm ghost" onClick={async () => { setTesting('…'); const t = await api.alertTest(); setTesting(`${t.page} · ${t.digest}`); q.refetch() }}>{testing ?? (r.dependencies.alert_test ? 'tested · re-test' : 'test')}</button>
              </div>
            </div>
            <div className="mut" style={{ fontSize: 12, marginTop: 10 }}>A missed heartbeat alerts within {lim.heartbeat_grace_min} minutes. Silence is treated as failure, never as "nothing happened".</div>
          </Panel>
          <Panel title="Control audit log" flat>
            <div id="audit" className="log">
              {r.audit.length === 0 && <span className="mut">No control actions yet.</span>}
              {r.audit.map(c => <div key={c.id}><span className="t">{dtET(c.at)}</span> {c.actor} · {c.action} {c.target}{c.before != null && c.after != null ? ` · ${JSON.stringify(c.before)} → ${JSON.stringify(c.after)}` : ''}{c.note ? ` · ${c.note}` : ''}</div>)}
            </div>
          </Panel>
        </div>
      </section>

      {modal === 'kill_all' && <ConfirmModal action="kill_all" title="Kill all bots" body="Cancels open orders, flattens every position at market on each bot's next run, disables all bots, and blocks new orders until re-armed." onDone={() => { setModal(null); q.refetch() }} onClose={() => setModal(null)} />}
      {modal === 'flatten_all' && <ConfirmModal action="flatten_all" title="Flatten all positions" body="Every bot closes its position at market on its next run. Bots stay enabled and may re-enter on a new signal." cls="warn" onDone={() => { setModal(null); q.refetch() }} onClose={() => setModal(null)} />}
      {modal === 'rearm' && <ConfirmModal action="rearm" title="Re-arm the fleet" body="Removes the kill flag and fleet pause. Confirm you have checked the account first." cls="warn" onDone={() => { setModal(null); q.refetch() }} onClose={() => setModal(null)} />}
      {edit && <div className="modal-bg" role="dialog" aria-modal="true"><div className="modal" style={{ borderColor: 'var(--line)' }}>
        <h2 style={{ fontSize: 16 }}>Edit limit · {edit.key}</h2>
        <label>New value (decimal: 0.06 = 6%)<br /><input value={edit.value} onChange={e => setEdit({ ...edit, value: e.target.value })} style={{ width: '100%', marginTop: 6 }} /></label>
        <label>Why (one line, goes in the audit log)<br /><input value={edit.note} onChange={e => setEdit({ ...edit, note: e.target.value })} style={{ width: '100%', marginTop: 6 }} /></label>
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}><button className="btn" onClick={() => setEdit(null)}>Cancel</button><button className="btn warn" disabled={!edit.note || isNaN(parseFloat(edit.value))} onClick={saveLimit}>Save</button></div>
      </div></div>}
    </main>
  )
}

function Dep({ name, ok, warn, val }: { name: string; ok: boolean; warn?: boolean; val: string }) {
  return <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, padding: '8px 10px', background: 'var(--bg)', borderRadius: 6 }}><span>{name}</span><span className={ok ? (warn ? 'warn' : 'pos') : 'neg'}>{val}</span></div>
}
