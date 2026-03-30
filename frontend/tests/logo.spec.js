import { test, expect } from '@playwright/test';

test.describe('WaterBot Logo', () => {
  test('splash page - logo text is visible', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');

    const logo = page.locator('.splash__topbar .wb-logo');
    await expect(logo).toBeVisible();
    await expect(logo).toContainText('Waterbot');

    await page.screenshot({ path: 'test-results/logo-home.png' });
  });

  test('chat page - header logo is visible', async ({ page }) => {
    await page.goto('/chat');
    await page.waitForLoadState('domcontentloaded');
    await page.waitForSelector('.app-header', { timeout: 10000 });

    const logo = page.locator('.app-header .wb-logo');
    await expect(logo).toBeVisible();
    await expect(logo).toContainText('Waterbot');

    await page.screenshot({ path: 'test-results/logo-chat.png' });
  });

  test('chat page - header has logo and action buttons', async ({ page }) => {
    await page.goto('/chat');
    await page.waitForLoadState('domcontentloaded');

    const header = page.locator('.app-header');
    await expect(header).toBeVisible();
    await expect(header.locator('.wb-logo')).toBeVisible();
    await expect(header.locator('.app-header__right')).toHaveCount(1);
  });
});
