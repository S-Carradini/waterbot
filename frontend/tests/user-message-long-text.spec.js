import { test, expect } from '@playwright/test';

const LONG_MESSAGE = 'This is a very long question to test if the input chat bubble breaks when the user types an extremely lengthy message that goes on and on without stopping. What happens to the Arizona water supply when there is a severe drought? How does the Colorado River affect our state? Can you tell me more about groundwater and aquifers? I want to understand the full picture of water management in our desert environment.';

test.describe('User Message Long Text', () => {
  test('long user message displays fully without cutoff or overflow', async ({ page }) => {
    await page.goto('/museum/chat');
    await page.waitForLoadState('domcontentloaded');

    const textbox = page.getByRole('textbox', { name: 'Type your question here' });
    await expect(textbox).toBeVisible();
    await textbox.fill(LONG_MESSAGE);

    await page.locator('button.paper-plane-icon-button').click();

    // Wait for user message bubble to appear
    const userQuery = page.locator('.user-query').last();
    await expect(userQuery).toBeVisible({ timeout: 5000 });

    // Assert full text is visible
    await expect(userQuery.locator('.question-text p')).toContainText(
      'This is a very long question to test if the input chat bubble breaks'
    );
    await expect(userQuery.locator('.question-text p')).toContainText(
      'full picture of water management in our desert environment'
    );

    // Assert no vertical cutoff: check question-text (polygon extends outside user-query)
    const questionText = userQuery.locator('.question-text');
    const verticalOk = await questionText.evaluate((el) => {
      const scrollH = el.scrollHeight;
      const clientH = el.clientHeight;
      const tolerance = 2;
      return scrollH <= clientH + tolerance;
    });
    expect(verticalOk).toBe(true);

    // Assert no horizontal overflow
    const horizontalOk = await questionText.evaluate((el) => {
      const scrollW = el.scrollWidth;
      const clientW = el.clientWidth;
      const tolerance = 2;
      return scrollW <= clientW + tolerance;
    });
    expect(horizontalOk).toBe(true);

    await page.screenshot({ path: 'test-results/user-message-long-text.png' });
  });
});
