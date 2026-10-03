import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api, type BotSummary } from '../lib/api'
import { money, pct, timeET } from '../lib/format'
import { Dot, ModeBadge, Panel, statusTone } from '../components/ui'

/** Directory of every registered bot: what it trades, how it's doing, where it is in the paper → live pipeline. */
export function BotsPage() {
  const q = useQuery({ queryKey: ['bots'], queryFn: api.bots, refetchInterval: 15000 })
  const bots = q.data ?? []
  const groups: [string, BotSummary[]][] = [
    ['Live', bots.filter(b => b.mode === 'live')],
    ['Paper — intraday', bots.filter(b => b.mode === 'paper' && 'session' in (b.cadence || {}))],
    ['Paper — daily', bots.filter(b => b.mode === 'paper' && !('session' in (b.cadence || {})))],
  ]
  return (
    <main>
      <h1 style={{ fontSize: 18 }}>Bots <span className="mut" style={{ fontSize: 13, fontWeight: 400 }}>· {bots.length} registered</span></h1>
      {q.isLoading && <div className="empty">Loading…</div>}
      {groups.filter(g => g[1].length).map(([title, list]) => (
        <section key={title} style={{ marginTop: 16 }}>
          <h2 className="mut" style={{ fontSize: 12, textTransform: 'uppercase', letterSpacing: '.06em', margin: '0 0 8px' }}>{title}</h2>
          <div className="grid2">
            {list.map(b => <BotCard key={b.id} b={b} />)}
          </div>
        </section>))}
      {q.data && bots.length === 0 && <div className="empty">No bots have run yet. A bot appears here after its first scheduled run or replay.</div>}
    </main>
  )
}

function BotCard({ b }: { b: BotSummary }) {
  const ps = (b.positions || []).filter(p => p.qty)
  const sched = Object.entries(b.cadence || {}).map(([k, v]) => `${k} ${v}`).join(' · ')
  return (
    <Panel title={b.name} meta={<span style={{ display: 'inline-flex', gap: 8, alignItems: 'center' }}><Dot tone={statusTone(b.status)} /><ModeBadge mode={b.mode} status={b.status} /><span className="mut">v{b.version}</span></span>}
      right={<Link className="btn sm" to={`/bots/${b.id}`}>Open →</Link>}>
      <div style={{ fontSize: 13, display: 'flex', flexDirection: 'column', gap: 6, padding: '10px 16px 14px' }}>
        <div>{b.strategy_line}</div>
        <div className="kv m">
          <b>Instrument</b><span className="mono">{b.instrument}</span>
          <b>Schedule</b><span className="mono">{sched || '—'} ET</span>
          <b>Position</b><span className="mono">{ps.length ? ps.map(p => `${p.qty > 0 ? 'L' : 'S'} ${Math.abs(p.qty)} ${p.symbol}`).join(', ') : 'flat'}</span>
          <b>Day P&L</b><span className={`mono ${b.day_pnl > 0 ? 'pos' : b.day_pnl < 0 ? 'neg' : 'mut'}`}>{b.day_pnl ? money(b.day_pnl) : '—'}</span>
          <b>Drawdown</b><span className="mono">{pct(-b.drawdown, 1)}</span>
          <b>Live vs backtest</b><span className={b.parity.verdict === 'drift' ? 'warn' : b.parity.verdict === 'within' ? 'pos' : 'mut'}>{b.parity.sentence || b.parity.verdict}</span>
          <b>Heartbeat</b><span className={b.heartbeat?.ok && b.status !== 'degraded' ? 'mut' : 'neg'}>{b.heartbeat ? `${b.heartbeat.run} ${timeET(b.heartbeat.at)} ${b.heartbeat.ok ? '✓' : '✗'}` : 'never'}</span>
        </div>
        {(b.flags.killed || b.flags.paused || b.flags.flatten) && <div className="warn" style={{ fontSize: 12 }}>
          {b.flags.killed ? 'Killed. ' : ''}{b.flags.paused ? 'Entries paused. ' : ''}{b.flags.flatten ? 'Flatten requested.' : ''}</div>}
      </div>
    </Panel>
  )
}
