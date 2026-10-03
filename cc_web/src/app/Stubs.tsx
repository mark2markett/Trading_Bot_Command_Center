import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import { dtET } from '../lib/format'
import { Dot, Panel } from '../components/ui'

/** v1 stub: alert history doubles as the journal until trade notes land in v2. */
export function JournalPage() {
  const q = useQuery({ queryKey: ['alerts'], queryFn: api.alerts, refetchInterval: 15000 })
  return (
    <main>
      <h1 style={{ fontSize: 18 }}>Journal</h1>
      <p className="mut" style={{ margin: 0, fontSize: 13 }}>v1 shows the alert history. Per-trade notes, tags and screenshots are scheduled for v2 (see docs/BACKLOG.md).</p>
      <Panel title="Alert history" meta={`${q.data?.length ?? 0} items`}>
        {(q.data ?? []).map(a => (
          <div className="item" key={a.id}><Dot tone={a.severity === 'page' ? 'neg' : a.severity === 'digest' ? 'warn' : 'acc'} />
            <div style={{ flex: 1 }}><b>{a.bot_name ? `${a.bot_name}: ` : ''}{a.kind.replace(/_/g, ' ')}</b><div className="body">{a.message}</div>
              <div className="src">{dtET(a.at)} ET · {a.severity}{a.acknowledged_at ? ' · acknowledged' : ''}</div></div>
            {!a.acknowledged_at && <button className="btn sm ghost" aria-label="acknowledge" onClick={() => api.ack(a.id).then(() => q.refetch())}>✓</button>}
          </div>))}
        {q.data?.length === 0 && <div className="empty">No alerts yet.</div>}
      </Panel>
    </main>
  )
}

/** v1 stub: the paper -> live promotion gates as a checklist. The research runner comes in v2. */
export function ResearchPage() {
  const q = useQuery({ queryKey: ['fleet'], queryFn: api.fleet })
  const gates = (b: NonNullable<typeof q.data>['bots'][number]) => [
    { name: '≥ 8 paper trades', ok: (b.parity.sentence.match(/(\d+) trades/) ? false : b.parity.verdict !== 'n/a') },
    { name: 'Parity within band', ok: b.parity.verdict === 'within' && !b.parity.sentence.includes('too few') },
    { name: 'No rejected orders in 24h', ok: b.rejected_24h === 0 },
    { name: 'Heartbeat healthy', ok: !!b.heartbeat?.ok && b.status !== 'degraded' },
    { name: 'Operator sign-off', ok: false },
  ]
  return (
    <main>
      <h1 style={{ fontSize: 18 }}>Research</h1>
      <p className="mut" style={{ margin: 0, fontSize: 13 }}>Promotion gates from paper to live. A bot goes live only when every gate is green and you sign off. The backtest runner and walk-forward grid are v2.</p>
      <div className="grid2">
        {(q.data?.bots ?? []).filter(b => b.mode === 'paper').map(b => (
          <Panel key={b.id} title={b.name} meta="paper → live gates" flat>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6, fontSize: 13 }}>
              {gates(b).map(g => <div key={g.name} style={{ display: 'flex', justifyContent: 'space-between' }}><span>{g.name}</span><span className={g.ok ? 'pos' : 'mut'}>{g.ok ? '✓' : '○'}</span></div>)}
            </div>
          </Panel>))}
        {q.data && q.data.bots.filter(b => b.mode === 'paper').length === 0 && <div className="empty">No paper bots to promote.</div>}
      </div>
    </main>
  )
}
