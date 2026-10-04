// Render the actual built app using local-only requests and an owned server identity.
import { createRequire } from 'node:module'
import { mkdir, writeFile } from 'node:fs/promises'
import path from 'node:path'

const require = createRequire(new URL('../cc_web/package.json', import.meta.url))
const { chromium } = require('@playwright/test')
const [base, output, nonce, pid] = process.argv.slice(2)
if (base !== 'http://127.0.0.1:8586' || !output || !nonce || !pid) {
  throw new Error('An owned sandbox URL and output directory are required')
}
await mkdir(output, { recursive: true })
const rows = []
let browser
try {
  const options = { headless: true }
  if (process.env.CC_PLAYWRIGHT_EXECUTABLE) options.executablePath = process.env.CC_PLAYWRIGHT_EXECUTABLE
  try {
    browser = await chromium.launch(options)
  } catch (error) {
    const absent = /Executable doesn't exist/.test(String(error?.message))
    rows.push({ name: 'Dashboard screenshots', outcome: absent ? 'NOT COVERED' : 'FAIL', evidence: absent ? 'Playwright browser unavailable; install Chromium or set CC_PLAYWRIGHT_EXECUTABLE' : 'Selected browser failed to launch', synthetic: true })
  }
  if (browser) {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
    const identity = await context.request.get(`${base}/__closed_loop_identity`)
    const body = await identity.json()
    if (identity.status() !== 200 || body.nonce !== nonce || body.pid !== Number(pid)) throw new Error('Server identity mismatch')
    await context.route('**/*', route => {
      const url = new URL(route.request().url())
      return url.origin === base ? route.continue() : route.abort()
    })
    const page = await context.newPage()
    const failures = []
    page.on('pageerror', () => failures.push('JavaScript page error'))
    page.on('response', response => {
      if (response.url().startsWith(`${base}/api/`) && response.status() >= 400) failures.push('Core API request failed')
    })
    await page.goto(base, { waitUntil: 'networkidle', timeout: 15000 })
    await page.getByText('5 configured · sorted by risk', { exact: true }).waitFor({ state: 'visible', timeout: 10000 })
    await page.screenshot({ path: path.join(output, 'fleet.png'), fullPage: true })
    rows.push({ name: 'Rendered fleet screenshot', outcome: failures.length ? 'FAIL' : 'PASS', evidence: failures.length ? failures.join('; ') : 'Actual app rendered five bots; fleet.png saved', synthetic: true })
    await page.goto(`${base}/bots/gap_go_spread`, { waitUntil: 'networkidle', timeout: 15000 })
    await page.getByRole('heading', { name: 'Gap-and-Go debit spread SPY/QQQ', exact: true }).waitFor({ state: 'visible', timeout: 10000 })
    await page.getByText(/SPY call spread/).first().waitFor({ state: 'visible', timeout: 10000 })
    await page.screenshot({ path: path.join(output, 'gap_go_spread.png'), fullPage: true })
    rows.push({ name: 'Rendered spread screenshot', outcome: failures.length ? 'FAIL' : 'PASS', evidence: failures.length ? failures.join('; ') : 'Actual spread, Greeks and DTE rendered; gap_go_spread.png saved', synthetic: true })
    const flatten = page.getByRole('button', { name: 'Flatten now…', exact: true })
    const enabled = await flatten.isEnabled()
    rows.push({ name: 'Spread flatten button', outcome: enabled ? 'PASS' : 'FAIL', evidence: enabled ? 'Open spread can be flattened from its actual operator button' : 'Product defect: Flatten now is disabled with two open option legs (BotPage uses single-position pos)', synthetic: true })
  }
} catch {
  rows.push({ name: 'Rendered dashboard', outcome: 'FAIL', evidence: 'Identity, rendering or screenshot assertion failed; application was not modified', synthetic: true })
} finally {
  if (browser) await browser.close()
  await writeFile(path.join(output, 'web-results.json'), JSON.stringify(rows, null, 2))
}
process.exitCode = rows.some(row => row.outcome === 'FAIL') ? 1 : 0
