import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { api, type BotDetail, type Position } from '../lib/api'
import { BotPage } from './BotPage'

// uPlot reads this browser API at import time; jsdom does not provide it.
vi.hoisted(() => {
  Object.defineProperty(window, 'matchMedia', { configurable: true, value: () => ({
    matches: false, addEventListener() {}, removeEventListener() {},
  }) })
})

const clients: QueryClient[] = []
afterEach(() => {
  cleanup()
  clients.splice(0).forEach(client => client.clear())
  vi.restoreAllMocks()
})

function position(qty: number, symbol = 'SPY'): Position {
  return { bot_id: 'gap_go_spread', symbol, qty, avg_price: 2, entry_at: null,
    bars_held: 0, updated_at: '2026-10-04T20:00:00Z' }
}

function renderBot(positions: Position[]) {
  const bot: BotDetail = {
    id: 'gap_go_spread', name: 'Gap-and-Go debit spread', strategy_line: 'Test spread',
    mode: 'paper', version: '1', instrument: 'SPY options', status: 'running',
    cadence: { session: 'RTH' }, position: null, positions, day_pnl: 0, drawdown: 0, equity: 10000,
    parity: { verdict: 'n/a', sentence: 'Insufficient history' }, heartbeat: null,
    flags: { killed: false, paused: false, flatten: false }, rejected_24h: 0,
    backtest: {}, limits: { max_position_usd: 10000, max_bot_dd: 0.1,
      max_consecutive_losses: 3, max_orders_per_day: 10, price_collar_pct: 0.01, stale_quote_s: 30 },
    parity_detail: { trades: 0, live: {}, flags: [], verdict: 'n/a', sentence: 'Insufficient history' },
    equity_series: [], expected: { median: [], lo: [], hi: [] }, trades: [], fills: [], decisions: [],
    usage: { orders_today: 0, consecutive_losses: 0 }, stop_price: null,
  }
  const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } })
  clients.push(client)
  client.setQueryData(['bot', bot.id], bot)
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/bots/gap_go_spread']}>
    <Routes><Route path="/bots/:id" element={<BotPage />} /></Routes>
  </MemoryRouter></QueryClientProvider>)
  return screen.getByRole('button', { name: 'Flatten now…' })
}

describe('Flatten eligibility', () => {
  it.each([
    ['no positions', []],
    ['only zero-quantity positions', [position(0), position(0, 'QQQ')]],
  ])('stays disabled with %s', (_name, positions) => {
    expect(renderBot(positions as Position[])).toBeDisabled()
  })

  it.each([10, -10])('allows a single open position with qty=%s', qty => {
    expect(renderBot([position(qty)])).toBeEnabled()
  })

  it('allows a two-leg spread through the existing confirmation dialog', async () => {
    // Only the external confirmation response is supplied; page/query/modal logic is real.
    vi.spyOn(api, 'confirmWord').mockResolvedValue({ word: 'CLOSE' })
    const flatten = renderBot([position(4, 'SPY261006C00500000'), position(-4, 'SPY261006C00505000')])
    expect(flatten).toBeEnabled()
    fireEvent.click(flatten)
    expect(screen.getByRole('dialog', { name: 'Flatten Gap-and-Go debit spread' })).toBeVisible()
    await screen.findByText('CLOSE', { selector: 'b' })
    const confirm = screen.getByRole('button', { name: 'Confirm' })
    expect(confirm).toBeDisabled()
    fireEvent.change(screen.getByLabelText('confirmation word'), { target: { value: 'WRONG' } })
    expect(confirm).toBeDisabled()
    fireEvent.change(screen.getByLabelText('confirmation word'), { target: { value: 'CLOSE' } })
    expect(confirm).toBeEnabled()
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
})
