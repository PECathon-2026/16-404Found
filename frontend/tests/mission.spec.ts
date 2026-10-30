/** Real browser interaction checks, with isolated HTTP fixtures for the future backend. */
import { expect, test } from '@playwright/test'

test('all five agent scenes open, switch, and restore keyboard focus', async ({ page }) => {
  const errors: string[] = []; page.on('pageerror', error => errors.push(error.message))
  await page.goto('/')
  const master = page.getByRole('button', { name: 'Focus on Master orchestration' })
  await master.click()
  for (const agent of ['Master', 'Architect', 'Engineer', 'Verifier', 'Sentinel']) {
    await page.getByRole('button', { name: `Focus ${agent}`, exact: true }).click()
    await expect(page.getByRole('dialog', { name: `${agent} focus mode` })).toBeVisible()
    await expect(page.locator('.focus-scene-wrap canvas')).toBeVisible()
  }
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(master).toBeFocused()
  expect(errors).toEqual([])
})

test('preview feedback and approval remain illustrative and make no API calls', async ({ page }) => {
  let requests = 0
  await page.route('**/missions/**', route => { requests++; return route.abort() })
  await page.goto('/')
  const advance = page.getByRole('button', { name: 'Advance preview one event' })
  for (let i = 0; i <= 6; i++) await advance.click()
  await page.getByRole('tab', { name: 'Tests', exact: true }).click()
  await expect(page.getByRole('tabpanel')).toContainText('total < 0')
  for (let i = 7; i <= 11; i++) await advance.click()
  await page.getByRole('tab', { name: 'Security', exact: true }).click()
  await expect(page.getByRole('tabpanel')).toContainText('open')
  for (let i = 12; i <= 14; i++) await advance.click()
  await expect(page.getByRole('tabpanel')).toContainText('resolved')
  await page.getByRole('button', { name: /Your move/ }).click()
  await expect(page.getByRole('dialog')).toContainText('No files will be applied')
  await page.getByRole('button', { name: 'Finish preview' }).click()
  await expect(page.getByRole('status')).toContainText('No repository was modified')
  expect(requests).toBe(0)
})

test('live approval sends patch identity and rejects stale evidence visibly', async ({ page }) => {
  const mission = {
    id: 'browser-test', request: 'Browser fixture request', repository: 'browser-fixture',
    phase: 'awaiting_human', activeAgent: 'master', events: [],
    criteria: [{ id: 'C1', text: 'Behavior verified', status: 'passed', evidence: 'Fixture check output' }],
    changes: [{ path: 'example.py', before: 'old', after: 'new' }],
    tests: [{ command: 'pytest', status: 'passed', output: 'Fixture test output' }], issues: [],
    approvalEligible: true, patchHash: 'browser-test-hash',
  }
  let submitted: unknown
  await page.route('http://127.0.0.1:8000/api/missions/**', async route => {
    if (route.request().method() === 'POST') {
      submitted = route.request().postDataJSON()
      await route.fulfill({ status: 409, json: { error: 'stale patch' } })
    } else await route.fulfill({ json: mission })
  })
  await page.goto('/')
  await page.getByRole('button', { name: 'Backend connection settings' }).click()
  await page.getByLabel('MISSION ID', { exact: true }).fill('browser-test')
  await page.getByRole('button', { name: 'Connect mission' }).click()
  await expect(page.getByRole('button', { name: /LIVE BACKEND/ })).toBeVisible()
  await page.getByRole('button', { name: /Your move/ }).click()
  await page.getByRole('button', { name: 'Approve change' }).click()
  await expect(page.getByRole('alert')).toContainText('Refresh the evidence')
  expect(submitted).toEqual({ decision: 'approve', patch_hash: 'browser-test-hash' })
})

test('imported JSONL renders its events without claiming tests passed', async ({ page }) => {
  await page.goto('/')
  await page.locator('input[type=file]').setInputFiles({
    name: 'browser-fixture.jsonl', mimeType: 'text/plain',
    buffer: Buffer.from(JSON.stringify({ agent: 'verifier', time: '2026-10-30T10:00:00Z', event_type: 'TEST_FAILURE', output_summary: 'Imported browser fixture failure' })),
  })
  await expect(page.getByRole('tabpanel')).toContainText('Imported browser fixture failure')
  await page.getByRole('tab', { name: 'Tests', exact: true }).click()
  await expect(page.getByRole('tabpanel')).toContainText('Test evidence will appear')
  await page.getByRole('button', { name: /Your move/ }).click()
  await expect(page.getByRole('button', { name: 'Approve change' })).toBeDisabled()
})

for (const width of [320, 390, 768]) {
  test(`layout works at ${width}px and respects reduced motion`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 })
    await page.emulateMedia({ reducedMotion: 'reduce' })
    await page.goto('/')
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await page.getByRole('button', { name: 'Focus on Master orchestration' }).click()
    await expect(page.getByRole('dialog', { name: 'Master focus mode' })).toBeVisible()
    expect(await page.locator('.focus-view').evaluate(el => el.scrollWidth <= innerWidth)).toBe(true)
    await page.getByRole('button', { name: 'Focus Sentinel', exact: true }).click()
    await expect(page.getByRole('dialog', { name: 'Sentinel focus mode' })).toBeVisible()
    await page.getByRole('button', { name: 'Close agent focus' }).click()
    await page.getByRole('button', { name: /New mission/ }).click()
    await expect(page.getByLabel('YOUR MISSION')).toBeVisible()
  })
}
