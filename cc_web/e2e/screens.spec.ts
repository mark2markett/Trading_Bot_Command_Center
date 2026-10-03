import { test, expect } from '@playwright/test'
const BASE = 'http://127.0.0.1:8585'
const shots = [['fleet', '/'], ['bot', '/bots/qqq_mr'], ['risk', '/risk'], ['journal', '/journal'], ['research', '/research']] as const

for (const [name, path] of shots) {
  test(`${name} renders`, async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', e => errors.push(e.message))
    await page.goto(BASE + path)
    await page.waitForTimeout(1500)
    await expect(page.locator('main')).toBeVisible()
    expect(errors, 'no runtime errors').toEqual([])
    await page.screenshot({ path: `../var/screens/${name}.png`, fullPage: true })
  })
}

test('fleet phone layout', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto(BASE + '/')
  await page.waitForTimeout(1500)
  await expect(page.getByRole('button', { name: /kill all/i })).toBeVisible()
  const box = await page.getByRole('button', { name: /kill all/i }).boundingBox()
  expect(box!.height).toBeGreaterThanOrEqual(44)
  await page.screenshot({ path: '../var/screens/fleet-phone.png', fullPage: true })
})

test('kill switch keyboard path reaches confirm', async ({ page }) => {
  await page.goto(BASE + '/')
  await page.waitForTimeout(1000)
  await page.getByRole('button', { name: /kill all/i }).focus()
  await page.keyboard.press('Enter')
  const dlg = page.getByRole('dialog')
  await expect(dlg).toBeVisible()
  await expect(dlg.getByRole('button', { name: 'Confirm' })).toBeDisabled()
  await page.keyboard.press('Escape').catch(() => {})
  await dlg.getByRole('button', { name: 'Cancel' }).click()
  await expect(dlg).toBeHidden()
})
