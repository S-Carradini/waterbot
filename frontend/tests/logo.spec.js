import { test, expect } from '@playwright/test';

test.describe('WaterSim Logo', () => {
  test('home page - logo is visible, contained, and not cut off', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');

    const logo = page.locator('.home-header-bar img').first();
    await expect(logo).toBeVisible();

    const objectFit = await logo.evaluate((el) => window.getComputedStyle(el).objectFit);
    const containerBox = await page.locator('.home-header-bar').first().boundingBox();
    const imgBox = await logo.boundingBox();

    expect(objectFit).toBe('contain');
    expect(imgBox?.width).toBeGreaterThan(0);
    expect(imgBox?.height).toBeGreaterThan(0);
    // Logo should fit within its container (no overflow/clipping)
    if (containerBox && imgBox) {
      expect(imgBox.width).toBeLessThanOrEqual(containerBox.width + 2);
      expect(imgBox.height).toBeLessThanOrEqual(containerBox.height + 2);
    }

    await page.screenshot({ path: 'test-results/logo-home.png' });
  });

  test('chat page - header logo is visible, contained, and not cut off', async ({ page }) => {
    await page.goto('/museum/chat');
    await page.waitForLoadState('domcontentloaded');
    await page.waitForSelector('.header-bar, .header-unit', { timeout: 10000 });

    const logo = page.locator('.header-bar-logo, .header-unit img').first();
    await expect(logo).toBeVisible();

    const objectFit = await logo.evaluate((el) => window.getComputedStyle(el).objectFit);
    const containerBox = await page.locator('.header-bar').first().boundingBox();
    const imgBox = await logo.boundingBox();

    expect(objectFit).toBe('contain');
    expect(imgBox?.width).toBeGreaterThan(0);
    expect(imgBox?.height).toBeGreaterThan(0);
    if (containerBox && imgBox) {
      expect(imgBox.width).toBeLessThanOrEqual(containerBox.width + 2);
      expect(imgBox.height).toBeLessThanOrEqual(containerBox.height + 2);
    }

    await page.screenshot({ path: 'test-results/logo-chat.png' });
  });

  test('chat page - header has logo and action buttons', async ({ page }) => {
    await page.goto('/museum/chat');
    await page.waitForLoadState('domcontentloaded');

    const header = page.locator('.header-unit');
    await expect(header).toBeVisible();
    await expect(header.locator('img[alt="WaterSimmersive"]')).toBeVisible();
    await expect(header.locator('.header-buttons-container')).toHaveCount(1);
  });
});
