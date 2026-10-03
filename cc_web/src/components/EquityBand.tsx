import { useEffect, useRef } from 'react'
import uPlot from 'uplot'
import 'uplot/dist/uPlot.min.css'

/** Live equity (solid) over the backtest expectation: median dashed, 5–95% band filled. x = trade index. */
export function EquityBand({ live, expected }: { live: number[]; expected: { median: number[]; lo: number[]; hi: number[] } }) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!ref.current) return
    const n = Math.max(live.length, expected.median.length)
    const x = Array.from({ length: n }, (_, i) => i)
    const pad = (a: number[]) => Array.from({ length: n }, (_, i) => (i < a.length ? a[i] : null))
    const u = new uPlot({
      width: ref.current.clientWidth || 600, height: 260,
      scales: { x: { time: false } },
      axes: [
        { stroke: '#8B949E', grid: { stroke: '#262C36' }, ticks: { stroke: '#262C36' }, font: '11px IBM Plex Mono', label: 'days', labelFont: '11px IBM Plex Sans', labelSize: 18 },
        { stroke: '#8B949E', grid: { stroke: '#262C36' }, ticks: { stroke: '#262C36' }, font: '11px IBM Plex Mono', size: 64, values: (_u, v) => v.map(x => '$' + (x / 1000).toFixed(0) + 'k') },
      ],
      series: [
        {},
        { label: 'hi', stroke: 'transparent', fill: '#1E2A3F', points: { show: false } },
        { label: 'lo', stroke: 'transparent', fill: '#1E2A3F', points: { show: false } },
        { label: 'backtest median', stroke: '#4C8DFF', width: 2, dash: [4, 4], points: { show: false } },
        { label: 'live', stroke: '#E6EDF3', width: 2.5, points: { show: false } },
      ],
      bands: [{ series: [1, 2], fill: '#1E2A3F' }],
      legend: { show: false }, cursor: { show: true },
    }, [x, pad(expected.hi), pad(expected.lo), pad(expected.median), pad(live)] as uPlot.AlignedData, ref.current)
    const ro = new ResizeObserver(() => u.setSize({ width: ref.current?.clientWidth || 600, height: 260 }))
    ro.observe(ref.current)
    return () => { ro.disconnect(); u.destroy() }
  }, [live, expected])
  return <div ref={ref} role="img" aria-label="Equity curve of the bot against the backtest expectation band" />
}
