import { describe, expect, it } from 'vitest'
import { cents, money, pct, signedMoney } from './format'

describe('format', () => {
  it('money', () => { expect(money(412380)).toBe('$412,380'); expect(money(-1304.39, 2)).toBe('−$1,304.39'); expect(money(null)).toBe('—') })
  it('signed', () => { expect(signedMoney(1942)).toBe('+$1,942'); expect(signedMoney(-1106)).toBe('−$1,106') })
  it('pct', () => { expect(pct(0.0047, 2, true)).toBe('+0.47%'); expect(pct(-0.031)).toBe('−3.1%'); expect(pct(0.77, 0)).toBe('77%') })
  it('cents', () => { expect(cents(0.006)).toBe('+0.6¢'); expect(cents(-0.01)).toBe('−1.0¢') })
})
