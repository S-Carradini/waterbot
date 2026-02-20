import { test, expect } from '@playwright/test';

test.describe('Microphone Button Animation', () => {
  test.beforeEach(async ({ page, context }) => {
    // Mock Speech Recognition — no onresult fired so auto-submit never triggers
    await context.addInitScript(() => {
      class MockSpeechRecognition {
        constructor() {
          this.continuous = false;
          this.interimResults = false;
          this.lang = 'en-US';
          this.maxAlternatives = 1;
          this.onresult = null;
          this.onerror = null;
          this.onend = null;
          this.onstart = null;
        }
        start() {
          if (this.onstart) this.onstart();
        }
        stop() {
          if (this.onend) this.onend();
        }
      }
      window.SpeechRecognition = MockSpeechRecognition;
      window.webkitSpeechRecognition = MockSpeechRecognition;
    });

    await page.goto('/museum/chat');
    await page.waitForLoadState('domcontentloaded');
    await page.waitForSelector('i.fa-microphone', { timeout: 10000 });
    await page.waitForTimeout(300);
  });

  test('should show recording modal when mic button is clicked', async ({ page }) => {
    const micButton = page.locator('button.header-dropdown-item:has(i.fa-microphone)');
    await expect(micButton).toBeVisible();

    // Modal backdrop should not exist initially
    const backdrop = page.locator('.recording-modal-backdrop');
    await expect(backdrop).not.toBeVisible();

    // Click the mic button
    await micButton.click();
    await page.waitForTimeout(300);

    // Mic button should have recording class
    await expect(micButton).toHaveClass(/recording/);

    // Recording modal backdrop should be visible
    await expect(backdrop).toBeVisible();

    // Stop button inside modal (scoped to avoid matching the mic button itself)
    const stopButton = page.locator('.recording-modal-container button[aria-label="Stop Recording"]');
    await expect(stopButton).toBeVisible();
  });

  test('should stop recording when stop button is clicked', async ({ page }) => {
    const micButton = page.locator('button.header-dropdown-item:has(i.fa-microphone)');
    const backdrop = page.locator('.recording-modal-backdrop');

    // Start recording
    await micButton.click();
    await page.waitForTimeout(300);
    await expect(micButton).toHaveClass(/recording/);
    await expect(backdrop).toBeVisible();

    // Click stop (scoped to modal to avoid matching the mic button's aria-label)
    const stopButton = page.locator('.recording-modal-container button[aria-label="Stop Recording"]');
    await stopButton.click();
    await page.waitForTimeout(400);

    // Recording should be stopped
    await expect(micButton).not.toHaveClass(/recording/);
    await expect(backdrop).not.toBeVisible();
  });

  test('should show Blue character and modal container when recording', async ({ page }) => {
    const micButton = page.locator('button.header-dropdown-item:has(i.fa-microphone)');
    await micButton.click();
    await page.waitForTimeout(300);

    // Modal container should be visible
    const modalContainer = page.locator('.recording-modal-container');
    await expect(modalContainer).toBeVisible();

    // Blue character SVG should be rendered inside the modal
    const blueCharacter = modalContainer.locator('svg').first();
    await expect(blueCharacter).toBeVisible();
  });
});
