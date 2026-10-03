import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import { dtET } from '../lib/format'
import { Dot, Panel } from '../components/ui'
import { Markdown } from '../components/Markdown'

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

/** Research: the committed results write-up, the latest local run, and the paper -> live gates per paper bot. */
export function ResearchPage() {
  const q = useQuery({ queryKey: ['fleet'], queryFn: api.fleet })
  const r = useQuery({ queryKey: ['research'], queryFn: api.research })
  const gates = (b: NonNullable<typeof q.data>['bots'][number]) => [
    { name: 'Parity within band', ok: b.parity.verdict === 'within' && !b.parity.sentence.includes('too few') },
    { name: 'No rejected orders in 24h', ok: b.rejected_24h === 0 },
    { name: 'Heartbeat healthy', ok: !!b.heartbeat?.ok && b.status !== 'degraded' },
    { name: 'Research bar met (PF ≥ 1.3, every fold positive, grid-stable)', ok: false },
    { name: 'Operator sign-off', ok: false },
  ]
  return (
    <main>
      <h1 style={{ fontSize: 18 }}>Research</h1>
      <p className="mut" style={{ margin: 0, fontSize: 13 }}>What was tested, what passed, and what each paper bot still has to prove. Re-run locally with <code className="mono">python -m research.run_all</code>; this page re-reads the files.</p>
      <div className="grid2" style={{ marginTop: 12 }}>
        {(q.data?.bots ?? []).filter(b => b.mode === 'paper').map(b => (
          <Panel key={b.id} title={b.name} meta="paper → live gates" flat>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6, fontSize: 13 }}>
              {gates(b).map(g => <div key={g.name} style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}><span>{g.name}</span><span className={g.ok ? 'pos' : 'mut'}>{g.ok ? '✓' : '○'}</span></div>)}
            </div>
          </Panel>))}
      </div>
      {r.data?.summary && r.data.summary_at && r.data.doc_at && r.data.summary_at > r.data.doc_at && <Panel title="Latest local run (newer than the write-up)" meta={r.data.summary_at ? `var/research/SUMMARY.md · ${dtET(r.data.summary_at)} ET` : undefined}>
        <Markdown text={r.data.summary} />
      </Panel>}
      <Panel title="Results write-up" meta={r.data?.doc_at ? `docs/RESEARCH_RESULTS.md · ${dtET(r.data.doc_at)} ET` : undefined}>
        {r.isLoading && <div className="empty">Loading…</div>}
        {r.data && !r.data.doc && <div className="empty">docs/RESEARCH_RESULTS.md not found.</div>}
        {r.data?.doc && <Markdown text={r.data.doc} />}
      </Panel>
    </main>
  )
}
