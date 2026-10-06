import { afterEach, expect, it } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { FleetPage } from './FleetPage'
import type { Fleet } from '../lib/api'

afterEach(cleanup)
it('shows unavailable account risk instead of zero exposure and drawdown', () => {
  const f = { equity: null, equity_series: [], day: { pnl: 0, pct: 0 }, daily_loss_limit_pct: .02,
    exposure: { usd: 0, ratio: 0, cap: 1.5 }, drawdown: { dd: 0, equity: null, peak: null, pause: .06, flatten: .08, kill: .1 },
    counts: {}, bots: [], attention: [], correlation: { ids: [], matrix: {}, flags: [] }, schedule: [], open_orders: [], fills: [],
  } as unknown as Fleet
  render(<MemoryRouter><FleetPage f={f} refetch={() => {}} /></MemoryRouter>)
  expect(screen.getByText(/Fleet risk unavailable/)).toBeInTheDocument()
  expect(screen.queryByText('0.00×')).not.toBeInTheDocument()
  expect(screen.queryByText('−0.0%')).not.toBeInTheDocument()
})
