import { describe, expect, it } from 'vitest'
import { cents, contractMultiplier, isOcc, money, pct, signedMoney, spreadLine } from './format'

describe('format', () => {
  it('money', () => { expect(money(412380)).toBe('$412,380'); expect(money(-1304.39, 2)).toBe('−$1,304.39'); expect(money(null)).toBe('—') })
  it('signed', () => { expect(signedMoney(1942)).toBe('+$1,942'); expect(signedMoney(-1106)).toBe('−$1,106') })
  it('pct', () => { expect(pct(0.0047, 2, true)).toBe('+0.47%'); expect(pct(-0.031)).toBe('−3.1%'); expect(pct(0.77, 0)).toBe('77%') })
  it('cents', () => { expect(cents(0.006)).toBe('+0.6¢'); expect(cents(-0.01)).toBe('−1.0¢') })
  it('options', () => {
    expect(isOcc('SPY   261009C00570000')).toBe(true); expect(isOcc('SPY')).toBe(false)
    expect(contractMultiplier('SPY   261009P00565000')).toBe(100); expect(contractMultiplier('QQQ')).toBe(1)
    expect(spreadLine({ underlying: 'SPY', right: 'C', expiry: '2026-10-09', qty: 19, legs: [], strikes: [570, 575], dte: 2,
      delta_shares: 380, theta_usd_day: -12.6, value_usd: 950, cost_usd: 988, unrealized_usd: -38, updated_at: '' }))
      .toBe('SPY call spread 570/575 ×19 · Δ +380 sh · θ −$13/day · 2 DTE')
    expect(spreadLine({ underlying: 'QQQ', right: 'P', expiry: '', qty: 3, legs: [], strikes: [482.5, 477.5], dte: 5,
      delta_shares: -91.4, theta_usd_day: 4, value_usd: 0, cost_usd: 0, unrealized_usd: 0, updated_at: '' }))
      .toBe('QQQ put spread 482.5/477.5 ×3 · Δ −91 sh · θ +$4/day · 5 DTE')
  })
})

