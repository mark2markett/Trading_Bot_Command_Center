import { useState } from 'react'
import { Link } from 'react-router-dom'
import type { BotSummary, Fleet } from '../lib/api'
import { api } from '../lib/api'
import { cents, dateET, money, pct, px, signedMoney, timeET, tone } from '../lib/format'
import { Dot, LimitBar, ModeBadge, Panel, Sparkline, Tile, statusTone } from '../components/ui'

type Filter = 'all' | 'live' | 'paper' | 'pos'

export function FleetPage({ f, refetch }: { f: Fleet; refetch: () => void }) {
  const [filter, setFilter] = useState<Filter>('all')
  const bots = f.bots.filter(b => filter === 'all' || (filter === 'live' && b.mode === 'live') || (filter === 'paper' && b.mode === 'paper') || (filter === 'pos' && b.position && b.position.qty))
  const dd = f.drawdown
  const dayRatio = Math.abs(Math.min(0, f.day.pct)) / (f.daily_loss_limit_pct || 0.02)
  return (
    <main>
      <section className="tiles">
        <Tile label="Portfolio equity" span2 value={<span>{money(f.equity)} <span style={{ fontSize: 14, fontWeight: 400 }} className={tone(f.day.pnl)}>{signedMoney(f.day.pnl)} today</span></span>} cls="xl">
          <Sparkline series={f.equity_series.map(e => e[1])} color={f.day.pnl >= 0 ? 'var(--pos)' : 'var(--neg)'} />
        </Tile>
        <Tile label="Day P&L vs limit" value={<span className={tone(f.day.pct)}>{pct(f.day.pct, 2, true)}</span>} sub={`Daily loss limit −${(f.daily_loss_limit_pct * 100).toFixed(1)}%`}>
          <LimitBar ratio={dayRatio} color={f.day.pct >= 0 ? 'var(--pos)' : undefined} />
        </Tile>
        <Tile label="Gross exposure" value={`${f.exposure.ratio.toFixed(2)}×`} sub={`Cap ${f.exposure.cap.toFixed(2)}× equity`}>
          <LimitBar ratio={f.exposure.ratio / f.exposure.cap} color="var(--accent)" />
        </Tile>
        <Tile label="Portfolio drawdown" value={<span className={dd.dd > dd.pause ? 'neg' : dd.dd > dd.pause / 2 ? 'warn' : ''}>−{(dd.dd * 100).toFixed(1)}%</span>} sub={`Pause at −${(dd.pause * 100).toFixed(0)}% · Kill at −${(dd.kill * 100).toFixed(0)}%`}>
          <LimitBar ratio={dd.dd / dd.kill} ticks={[{ at: dd.pause / dd.kill, color: 'var(--warn)' }, { at: dd.flatten / dd.kill, color: 'var(--neg)' }]} />
        </Tile>
        <Tile label="Fleet health">
          <div style={{ display: 'flex', gap: 14, marginTop: 8 }} className="mono">
            <div><div style={{ fontSize: 22, fontWeight: 600 }} className="pos">{f.counts.running || 0}</div><div style={{ fontSize: 11 }} className="mut">running</div></div>
            <div><div style={{ fontSize: 22, fontWeight: 600 }} className="warn">{f.counts.degraded || 0}</div><div style={{ fontSize: 11 }} className="mut">degraded</div></div>
            <div><div style={{ fontSize: 22, fontWeight: 600 }} className="mut">{(f.counts.paused || 0) + (f.counts.killed || 0)}</div><div style={{ fontSize: 11 }} className="mut">paused</div></div>
          </div>
        </Tile>
      </section>

      <section className="row">
        <div className="main">
          <Panel title="Bots" meta={`${f.bots.length} configured · sorted by risk`} right={(['all', 'live', 'paper', 'pos'] as Filter[]).map(k => (
            <button key={k} className={`btn sm ${filter === k ? '' : 'ghost'}`} onClick={() => setFilter(k)}>{k === 'pos' ? 'In position' : k[0].toUpperCase() + k.slice(1)}</button>))}>
            {bots.length === 0 && <div className="empty">No bots yet. A bot appears here after its first run with the SDK.</div>}
            {bots.length > 0 && <>
              <div className="scroll bots-table">
                <table style={{ minWidth: 860 }}>
                  <thead><tr><th>Bot</th><th>Mode</th><th>Position</th><th className="r">Day P&L</th><th className="r">DD</th><th>Live vs backtest</th><th>Heartbeat</th><th></th></tr></thead>
                  <tbody>{bots.map(b => <BotRow key={b.id} b={b} />)}</tbody>
                </table>
              </div>
              <div className="cards">{bots.map(b => <BotCard key={b.id} b={b} />)}</div>
            </>}
          </Panel>
        </div>
        <aside className="side">
          <Panel title="Needs attention" right={<span className="pill">{f.attention.length}</span>}>
            {f.attention.length === 0 && <div className="empty" style={{ padding: 20 }}>Nothing open.</div>}
            {f.attention.map(a => (
              <div className="item" key={a.id}>
                <Dot tone={a.severity === 'page' ? 'neg' : a.kind === 'calendar' ? 'acc' : 'warn'} />
                <div style={{ flex: 1 }}>
                  <b>{a.bot_name ? `${a.bot_name}: ` : ''}{a.kind.replace(/_/g, ' ')}</b>
                  <div className="body">{a.message}</div>
                  <div className="src">{timeET(a.at)} ET · {a.severity}</div>
                </div>
                <button className="btn sm ghost" aria-label="acknowledge" onClick={() => api.ack(a.id).then(refetch)}>✓</button>
              </div>
            ))}
          </Panel>
          <div className="corrwrap"><Correlation c={f.correlation} names={Object.fromEntries(f.bots.map(b => [b.id, b.name]))} /></div>
        </aside>
      </section>

      <section className="grid3">
        <Panel title="Today's schedule" flat>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, fontSize: 13 }}>
            {f.schedule.length === 0 && <span className="mut">No scheduled runs registered.</span>}
            {f.schedule.map((s, i) => <div key={i} style={{ display: 'flex', gap: 10 }}><span className="mono mut" style={{ width: 56 }}>{s.time}</span><span className={s.done ? 'pos' : 'mut'}>{s.done ? '✓' : '○'}</span><span>{s.bot} · {s.run}</span></div>)}
          </div>
        </Panel>
        <Panel title="Open orders" flat>
          <div className="mono" style={{ display: 'flex', flexDirection: 'column', gap: 8, fontSize: 13 }}>
            {f.open_orders.length === 0 && <span className="mut sans">None resting.</span>}
            {f.open_orders.map(o => <div key={o.id} style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}><span>{o.symbol} · {o.type} {o.qty}{o.stop_price ? ` @ ${px(o.stop_price)}` : ''}</span><span className="mut">{o.bot_name}</span></div>)}
          </div>
        </Panel>
        <Panel title="Recent fills" flat>
          <div className="mono" style={{ display: 'flex', flexDirection: 'column', gap: 8, fontSize: 13 }}>
            {f.fills.length === 0 && <span className="mut sans">No fills yet.</span>}
            {f.fills.map(x => <div key={x.id} style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}><span>{dateET(x.at)} · {x.symbol} {x.side} {x.qty} {x.type}</span><span>{px(x.price)} <span className={Math.abs(x.slippage) > 0.02 ? 'warn' : 'pos'}>{cents(x.slippage)}</span></span></div>)}
            {f.fills.length > 0 && <div className="sans mut" style={{ fontSize: 12, marginTop: 4 }}>Slippage vs backtest assumption (1¢): avg {cents(f.fills.reduce((a, x) => a + Math.abs(x.slippage), 0) / f.fills.length)} over {f.fills.length} fills.</div>}
          </div>
        </Panel>
      </section>
    </main>
  )
}

function Verdict({ b }: { b: BotSummary }) {
  const v = b.parity.verdict
  if (b.status === 'killed') return <span className="neg">✗ killed</span>
  if (v === 'drift') return <span className="warn">⚠ {b.parity.sentence}</span>
  if (v === 'within') return <span className={b.parity.sentence.includes('too few') ? 'mut' : 'pos'}>{b.parity.sentence.includes('too few') ? b.parity.sentence : '✓ within band'}</span>
  return <span className="mut">no trades · n/a</span>
}

function Heart({ b }: { b: BotSummary }) {
  if (!b.heartbeat) return <span className="neg">never</span>
  const ok = b.heartbeat.ok === 1
  return <span className={ok && b.status !== 'degraded' ? 'mut' : 'neg'}>{timeET(b.heartbeat.at)} {ok ? '✓' : '✗ failed'}</span>
}

function Pos({ b }: { b: BotSummary }) {
  if (b.position && b.position.qty) return <>LONG {b.position.qty} · {b.position.bars_held}/10 bars</>
  return <span className="mut">flat</span>
}

function BotRow({ b }: { b: BotSummary }) {
  return (
    <tr className={b.status === 'degraded' ? 'degraded' : b.status === 'paused' || b.status === 'killed' ? 'dim' : ''}>
      <td><Link to={`/bots/${b.id}`} className="sans" style={{ display: 'flex', alignItems: 'center', gap: 10, color: 'var(--fg)' }}><Dot tone={statusTone(b.status)} lg /><span><span style={{ fontWeight: 600 }}>{b.name}</span><br /><span className="mut" style={{ fontSize: 12 }}>{b.strategy_line}</span></span></Link></td>
      <td><ModeBadge mode={b.mode} status={b.status} /></td>
      <td><Pos b={b} /></td>
      <td className={`r ${tone(b.day_pnl)}`}>{b.day_pnl ? signedMoney(b.day_pnl) : '—'}</td>
      <td className={`r ${b.drawdown > 0.04 ? 'warn' : ''}`}>{b.drawdown ? `−${(b.drawdown * 100).toFixed(1)}%` : '0.0%'}</td>
      <td className="sans"><Verdict b={b} /></td>
      <td><Heart b={b} /></td>
      <td className="r sans"><Link to={`/bots/${b.id}`} style={{ fontSize: 12 }}>Open →</Link></td>
    </tr>
  )
}

function BotCard({ b }: { b: BotSummary }) {
  return (
    <Link to={`/bots/${b.id}`} className="card" style={{ color: 'var(--fg)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}><Dot tone={statusTone(b.status)} lg /><b>{b.name}</b><span style={{ marginLeft: 'auto' }}><ModeBadge mode={b.mode} status={b.status} /></span></div>
      <div className="mono" style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13 }}><span><Pos b={b} /></span><span className={tone(b.day_pnl)}>{b.day_pnl ? signedMoney(b.day_pnl) : '—'}</span></div>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12 }}><Verdict b={b} /><Heart b={b} /></div>
    </Link>
  )
}

function Correlation({ c, names }: { c: Fleet['correlation']; names: Record<string, string> }) {
  const ids = c.ids
  const short = (id: string) => (names[id] || id).replace(/Daily |Mean Reversion/g, '').slice(0, 9)
  const cell = (r: number) => Math.abs(r) >= 0.9 ? { background: 'var(--accent)', color: '#0E1116' } : Math.abs(r) >= 0.7 ? { background: '#3A6BC2', color: '#fff' } : Math.abs(r) >= 0.3 ? { background: 'var(--band)' } : { background: '#1A2130' }
  return (
    <Panel title="Strategy correlation · 60d" flat>
      {ids.length < 2 && <div className="mut" style={{ fontSize: 12 }}>Needs at least two bots with 10+ days of equity history.</div>}
      {ids.length >= 2 && <div className="corr" style={{ gridTemplateColumns: `90px repeat(${ids.length}, minmax(0,1fr))` }}>
        <div className="h" />{ids.map(i => <div key={i} className="h">{short(i)}</div>)}
        {ids.map(i => <>{<div key={i + 'l'} className="h lbl">{short(i)}</div>}{ids.map(j => <div key={i + j} style={cell(c.matrix[i][j])}>{c.matrix[i][j].toFixed(2)}</div>)}</>)}
      </div>}
      {c.flags.map((s, i) => <div key={i} className="warn" style={{ fontSize: 12, marginTop: 10 }}>{s}</div>)}
    </Panel>
  )
}
