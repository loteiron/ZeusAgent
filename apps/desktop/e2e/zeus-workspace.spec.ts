import { expect, test } from './test'
import { setupMockBackend, setupNoProvider, waitForAppReady } from './fixtures'

test('Zeus workspace remains usable across both appearances and a real chat turn', async ({}, testInfo) => {
  test.setTimeout(180_000)
  const fixture = await setupMockBackend()
  try {
    const { page } = fixture
    await page.emulateMedia({ colorScheme: 'light', reducedMotion: 'reduce' })
    await waitForAppReady(fixture, 120_000)
    await expect(page.locator('.z-welcome h1')).toBeVisible()
    await expect(page.locator('html')).toHaveAttribute('data-zeus-mode', 'light')
    await expect(page.locator('.z-sidebar-brand')).toBeVisible()
    await page.screenshot({ path: testInfo.outputPath('workspace-light.png') })

    await page.emulateMedia({ colorScheme: 'dark', reducedMotion: 'reduce' })
    await expect(page.locator('html')).toHaveAttribute('data-zeus-mode', 'dark')
    await page.screenshot({ path: testInfo.outputPath('workspace-dark.png') })

    const composer = page.locator('[contenteditable="true"]').first()
    await composer.click()
    await composer.pressSequentially('Hello, can you hear me?', { delay: 20 })
    await page.keyboard.press('Enter')
    await expect(page.getByText(/Hello from the mock inference server!/).first()).toBeVisible({ timeout: 60_000 })
    await page.screenshot({ path: testInfo.outputPath('conversation-dark.png') })
    await page.emulateMedia({ colorScheme: 'light', reducedMotion: 'reduce' })
    await expect(page.locator('html')).toHaveAttribute('data-zeus-mode', 'light')
    await page.screenshot({ path: testInfo.outputPath('conversation-light.png') })
  } finally {
    await fixture.cleanup()
  }
})

test('provider setup stays reachable on wide and compact windows', async ({}, testInfo) => {
  test.setTimeout(180_000)
  const fixture = await setupNoProvider()
  try {
    const { page } = fixture
    await page.emulateMedia({ colorScheme: 'light', reducedMotion: 'reduce' })
    const heading = page.locator('.z-onboarding-heading h2')
    await expect(heading).toBeVisible({ timeout: 120_000 })
    await expect(page.locator('.z-onboarding-form').getByRole('button').first()).toBeVisible({ timeout: 120_000 })
    await page.screenshot({ path: testInfo.outputPath('setup-light.png') })
    await page.emulateMedia({ colorScheme: 'dark', reducedMotion: 'reduce' })
    await expect(page.locator('html')).toHaveAttribute('data-zeus-mode', 'dark')
    await page.screenshot({ path: testInfo.outputPath('setup-dark.png') })

    await fixture.app.evaluate(({ BrowserWindow }) => {
      const window = BrowserWindow.getAllWindows()[0]
      window.setMinimumSize(480, 360)
      window.setContentSize(680, 500)
    })
    await expect(heading).toBeVisible()
    const lastAction = page.locator('.z-onboarding-form button').last()
    await lastAction.scrollIntoViewIfNeeded()
    await expect(lastAction).toBeInViewport()
    expect(await page.locator('.z-onboarding-card').evaluate(el => el.scrollWidth <= el.clientWidth + 1)).toBe(true)
    await page.screenshot({ path: testInfo.outputPath('setup-compact.png') })
  } finally {
    await fixture.cleanup()
  }
})
