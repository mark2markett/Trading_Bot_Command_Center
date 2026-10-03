import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api, type BotDetail } from '../lib/api'
import { agoMin, cents, dateET, dtET, money, pct, px, signedMoney, timeET, tone } from '../lib/format'
import { ConfirmModal, Dot, LimitBar, ModeBadge, Panel, Tile, statusTone } from '../components/ui'
import { EquityBand } from '../components/EquityBand'

export function BotPage() {
  const { id = '' } = useParams()
  const q = useQuery({ queryKey: ['bot', id], queryFn: () => api.bot(id), refetchInterval: 15000 })
  const [modal, setModal] = useState<null | 'flatten' | 'kill'>(null)
  if (q.isLoading) return <main><div className="empty">Loading…</div></main>
  if (q.error || !q.data) return <main><div className="empty neg">Could not load bot: {String(q.error)}</div></main>
  const b: BotDetail = q.data
  const ps = (b.positions || []).filter(p => p.qty)
  const pos = ps.length === 1 ? ps[0] : null
  const intraday = 'session' in (b.cadence || {})
  const lastDecide = b.decisions.find(d => d.run === 'decide') ?? (intraday ? b.decisions[0] : undefined)
  const sig = (lastDecide?.signal || {}) as Record<string, number | null>
  const live = b.equity_series.map(e => e[1])
  const act = (action: string, note = '') => api.control(`bot/${id}/${action}`, { note }).then(() => q.refetch())
  const limits = b.limits
  const posUsd = ps.reduce((a, p) => a + Math.abs(p.qty) * (p.avg_price || 0), 0)
  const unreal = pos && pos.avg_price && sig.price ? (sig.price / pos.avg_price - 1) : null
  return (
    <main>
      <header className="hdr" style={{ padding: 0, border: 0 }}>
        <Link to="/" className="chip">‹ Fleet</Link><span className="mut">/</span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <Dot tone={statusTone(b.status)} lg /><h1 style={{ fontSize: 18, fontWeight: 700 }}>{b.name}</h1><ModeBadge mode={b.mode} status={b.status} />
          <span className="mut" style={{ fontSize: 12 }}>v{b.version} · {b.strategy_line}</span>
        </div>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <button className="btn" onClick={() => act('rerun', 'check')}>Re-check signal</button>
          {b.flags.paused ? <button className="btn" onClick={() => act('resume')}>Resume entries</button> : <button className="btn" onClick={() => act('pause', 'pause after exit')}>Pause after exit</button>}
          <button className="btn warn" onClick={() => setModal('flatten')} disabled={!pos}>Flatten now…</button>
          <button className="btn danger" onClick={() => setModal('kill')}>Kill bot…</button>
        </div>
      </header>

      <section className="tiles c4">
        <Tile label={ps.length > 1 ? `Positions · ${ps.length} open` : 'Position'}
          value={ps.length > 1 ? <span className="pos">{ps.length} symbols</span> : pos ? <span className="pos">{pos.qty > 0 ? 'LONG' : 'SHORT'} {Math.abs(pos.qty)} {pos.symbol || b.instrument}</span> : <span className="mut" style={{ fontFamily: 'var(--font)' }}>FLAT</span>}
          sub={pos ? undefined : b.trades[0] ? `Last trade closed ${dateET(b.trades[0].exit_at)} · ${pct(b.trades[0].exit_px / b.trades[0].entry_px - 1, 1, true)}${b.trades[0].bars ? ` in ${b.trades[0].bars} bars` : ''}` : 'No trades yet'}>
          {ps.length > 1 && <table className="tbl" style={{ marginTop: 6, fontSize: 12 }}><tbody>
            {ps.map(p => <tr key={p.symbol}><td className="mono">{p.qty > 0 ? 'L' : 'S'} {Math.abs(p.qty)} {p.symbol}</td><td className="mono">@ {px(p.avg_price)}</td><td className="mono mut">stop {p.stop_price ? px(p.stop_price) : '—'}</td></tr>)}
          </tbody></table>}
          {ps.length === 1 && pos && <div className="kv" style={{ marginTop: 6 }}>
            <b>Entry</b><span className="mono">{dateET(pos.entry_at)} @ {px(pos.avg_price)}</span>
            {intraday ? <><b>Stop</b><span className="mono">{px(pos.stop_price ?? null)}</span></> : <><b>Bars held</b><span className="mono">{pos.bars_held} / {limits.max_bars ?? 10}</span>
            <b>Crash stop</b><span className="mono">{px(b.stop_price)}</span></>}
            <b>Unrealized</b><span className={`mono ${unreal != null ? tone(unreal) : ''}`}>{pct(unreal, 2, true)}</span>
          </div>}
          {b.flags.flatten && <div className="warn" style={{ fontSize: 12, marginTop: 8 }}>Flatten requested · executes on next run</div>}
        </Tile>
        <Tile label={`Signal · last ${intraday ? 'session event' : 'decide'} ${lastDecide ? timeET(lastDecide.at) + ' ET' : ''}`}>
          {Object.keys(sig).length === 0 && <div className="mut" style={{ marginTop: 6 }}>{intraday ? 'No session events yet.' : 'No decide run recorded yet.'}</div>}
          {intraday && lastDecide && <div className="kv m" style={{ marginTop: 6 }}><b>Event</b><span>{lastDecide.action}</span><b>Why</b><span>{lastDecide.reason}</span>{Object.entries(sig).slice(0, 4).map(([k, v]) => <><b key={k}>{k}</b><span key={k + 'v'} className="mono">{typeof v === 'number' ? v.toFixed(2) : String(v)}</span></>)}</div>}
          {!intraday && Object.keys(sig).length > 0 && <>
            <div className="kv m" style={{ marginTop: 6 }}>
              {'price' in sig && <><b>Price</b><span>{px(sig.price)}</span></>}
              {'rsi2' in sig && <><b>RSI(2)</b><span className={(sig.rsi2 ?? 99) < 10 ? 'pos' : ''}>{sig.rsi2?.toFixed(1)} <span className="mut">· buy &lt; 10</span></span></>}
              {'sma200' in sig && <><b>SMA200</b><span className={(sig.price ?? 0) > (sig.sma200 ?? 0) ? 'pos' : 'neg'}>{px(sig.sma200)} · {(sig.price ?? 0) > (sig.sma200 ?? 0) ? 'above ✓' : 'BELOW'}</span></>}
              {'sma5' in sig && <><b>SMA5</b><span>{px(sig.sma5)}</span></>}
            </div>
            {'rsi2' in sig && sig.rsi2 != null && <div className="rail" aria-hidden="true"><i style={{ left: '10%' }} /><b style={{ left: `${Math.min(100, Math.max(0, sig.rsi2))}%` }} /></div>}
            {'rsi2' in sig && <div className="sub">{(sig.rsi2 ?? 99) < 10 ? 'Entry condition met' : 'Needs sharp down closes to reach the entry zone'}</div>}
          </>}
        </Tile>
        <Tile label="Allocated equity" value={money(b.equity ?? limits.max_position_usd)} sub={`Max position ${money(limits.max_position_usd)} · ${limits.max_orders_per_day} orders/day · Schwab`} />
        <Tile label="Health">
          <div style={{ display: 'flex', flexDirection: 'column', gap: 5, marginTop: 8, fontSize: 13 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}><span>Heartbeat {b.heartbeat?.run}</span><span className={b.heartbeat?.ok ? 'pos' : 'neg'}>{b.heartbeat ? `${b.heartbeat.ok ? '✓' : '✗'} ${agoMin(b.heartbeat.at)} min ago` : 'never'}</span></div>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}><span>Rejected orders 24h</span><span className={b.rejected_24h ? 'neg' : 'pos'}>{b.rejected_24h}</span></div>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}><span>Control flags</span><span className={b.flags.killed ? 'neg' : b.flags.paused ? 'warn' : 'pos'}>{b.flags.killed ? 'killed' : b.flags.paused ? 'paused' : 'clear'}</span></div>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}><span>Next run</span><span className="mono">{Object.entries(b.cadence).map(([k, v]) => `${v} ${k}`).join(' · ') || '—'}</span></div>
          </div>
        </Tile>
      </section>

      <section className="row stretch">
        <div className="main panel flat">
          <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 12, marginBottom: 8 }}>
            <h2>Live vs backtest expectation</h2>
            <div className="mut" style={{ display: 'flex', gap: 14, fontSize: 12, marginLeft: 'auto' }}>
              <span><span style={{ display: 'inline-block', width: 14, height: 3, background: 'var(--fg)', verticalAlign: 'middle', marginRight: 6 }} />live / paper</span>
              <span><span style={{ display: 'inline-block', width: 14, height: 3, background: 'var(--accent)', verticalAlign: 'middle', marginRight: 6 }} />backtest median</span>
              <span><span style={{ display: 'inline-block', width: 14, height: 10, background: 'var(--band)', verticalAlign: 'middle', marginRight: 6 }} />5–95% band</span>
            </div>
          </div>
          <EquityBand live={live} expected={b.expected} />
          <div className="stats">
            <div className="stat"><div className="lbl">Trades</div><div>{b.parity_detail.trades} <span className="mut">/ ~{b.backtest?.trades_per_year ?? '?'} yr</span></div></div>
            <div className="stat"><div className="lbl">Win rate</div><div className={b.parity_detail.verdict === 'drift' ? 'warn' : 'pos'}>{b.parity_detail.live.win_rate != null ? pct(b.parity_detail.live.win_rate, 0) : '—'} <span className="mut">/ {pct(b.backtest?.win_rate, 0)}</span></div></div>
            <div className="stat"><div className="lbl">Avg win / loss</div><div>{pct(b.parity_detail.live.avg_win, 1, true)} <span className="mut">/ {pct(b.backtest?.avg_win, 2, true)}</span><br />{pct(b.parity_detail.live.avg_loss, 1, true)} <span className="mut">/ {pct(b.backtest?.avg_loss, 2, true)}</span></div></div>
            <div className="stat"><div className="lbl">Slippage / fill</div><div className={(b.parity_detail.live.slippage ?? 0) > (b.backtest?.slippage_assumed ?? 0.01) * 2 ? 'warn' : 'pos'}>{b.parity_detail.live.slippage != null ? `${(b.parity_detail.live.slippage * 100).toFixed(1)}¢` : '—'} <span className="mut">/ {((b.backtest?.slippage_assumed ?? 0.01) * 100).toFixed(0)}¢ assumed</span></div></div>
            <div className="stat"><div className="lbl">Parity verdict</div><div className={b.parity_detail.verdict === 'drift' ? 'warn' : b.parity_detail.verdict === 'within' ? 'pos' : 'mut'}>{b.parity_detail.sentence}</div></div>
          </div>
        </div>
        <div className="side">
          <Panel title="Risk limits · this bot" flat>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 9, fontSize: 13 }}>
              <div><div style={{ display: 'flex', justifyContent: 'space-between' }}><span>Max position</span><span className="mono">{money(posUsd)} / {money(limits.max_position_usd)}</span></div><LimitBar thin ratio={posUsd / limits.max_position_usd} color="var(--accent)" /></div>
              <div><div style={{ display: 'flex', justifyContent: 'space-between' }}><span>Bot drawdown</span><span className="mono">−{(b.drawdown * 100).toFixed(1)}% / −{(limits.max_bot_dd * 100).toFixed(0)}%</span></div><LimitBar thin ratio={b.drawdown / limits.max_bot_dd} /></div>
              <div><div style={{ display: 'flex', justifyContent: 'space-between' }}><span>Consecutive losses</span><span className="mono">{b.usage.consecutive_losses} / {limits.max_consecutive_losses} → auto-pause</span></div><LimitBar thin ratio={b.usage.consecutive_losses / limits.max_consecutive_losses} /></div>
              <div><div style={{ display: 'flex', justifyContent: 'space-between' }}><span>Orders today</span><span className="mono">{b.usage.orders_today} / {limits.max_orders_per_day} max</span></div><LimitBar thin ratio={b.usage.orders_today / limits.max_orders_per_day} color="var(--accent)" /></div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}><span>Price collar on MOC</span><span className="mono">±{(limits.price_collar_pct * 100).toFixed(1)}% of quote</span></div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}><span>Stale-data guard</span><span className="mono">skip if quote &gt; {limits.stale_quote_s}s old</span></div>
            </div>
          </Panel>
          <Panel title="Parameters" flat>
            <div className="kv"><b>Backtest</b><span className="mono">PF {b.backtest?.profit_factor ?? '—'} · DD {pct(b.backtest?.max_dd, 1)}</span>
              <b>Cadence</b><span className="mono">{Object.entries(b.cadence).map(([k, v]) => `${k} ${v}`).join(' · ')} ET</span>
              <b>Version</b><span className="mono">v{b.version}</span></div>
            <div className="mut" style={{ fontSize: 12, marginTop: 10 }}>Rules live in the bot's code and are frozen. A version bump resets the parity band start.</div>
          </Panel>
        </div>
      </section>

      <section className="row">
        <div className="main">
          <Panel title="Trades" meta={`${b.mode} · ${b.trades.length} closed`} right={<a className="btn sm ghost" href={`data:text/csv,${encodeURIComponent(csv(b))}`} download={`${b.id}_trades.csv`}>Export CSV</a>}>
            {b.trades.length === 0 && <div className="empty">No closed trades yet. This strategy fires about {b.backtest?.trades_per_year ?? 'a few'} times a year; a quiet table is normal.</div>}
            {b.trades.length > 0 && <div className="scroll"><table style={{ minWidth: 680 }}>
              <thead><tr><th>Entry</th><th>Exit</th><th>Qty</th><th>In → Out</th><th>Bars</th><th>Reason</th><th className="r">P&L</th><th className="r">Slip</th></tr></thead>
              <tbody>{b.trades.map(t => <tr key={t.id}><td>{dateET(t.entry_at)}</td><td>{dateET(t.exit_at)}</td><td>{t.qty}</td><td>{px(t.entry_px)} → {px(t.exit_px)}</td><td>{t.bars}</td><td className={t.exit_reason.includes('stop') ? 'warn' : 'mut'}>{t.exit_reason}</td><td className={`r ${tone(t.pnl)}`}>{signedMoney(t.pnl)}</td><td className="r mut">{cents(t.slippage)}</td></tr>)}</tbody>
            </table></div>}
          </Panel>
        </div>
        <div className="side">
          <Panel title="Decision log" meta="every run, every reason">
            <div className="pb log">
              {b.decisions.length === 0 && <span className="mut">Nothing yet.</span>}
              {b.decisions.map(d => <div key={d.id}><span className="t">{dtET(d.at)}</span> {d.run} · <span className={d.action.includes('BUY') || d.action.includes('SELL') ? 'warn' : d.action === 'RECONCILE' ? 'pos' : ''}>{d.action}</span> · {d.reason}</div>)}
            </div>
          </Panel>
        </div>
      </section>

      {modal === 'flatten' && <ConfirmModal action={`flatten:${id}`} title={`Flatten ${b.name}`} body="Closes the position at market on the bot's next run (immediately if the market is open and the bot is triggered). Keeps the bot enabled." cls="warn" onDone={() => { setModal(null); q.refetch() }} onClose={() => setModal(null)} />}
      {modal === 'kill' && <ConfirmModal action={`kill:${id}`} title={`Kill ${b.name}`} body="Flattens its position and disables this bot until a person resumes it." onDone={() => { setModal(null); q.refetch() }} onClose={() => setModal(null)} />}
    </main>
  )
}

function csv(b: BotDetail): string {
  const h = 'entry_at,exit_at,qty,entry_px,exit_px,bars,exit_reason,pnl,slippage'
  return [h, ...b.trades.map(t => [t.entry_at, t.exit_at, t.qty, t.entry_px, t.exit_px, t.bars, t.exit_reason, t.pnl, t.slippage].join(','))].join('\n')
}
