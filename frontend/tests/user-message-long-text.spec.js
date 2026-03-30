import { test, expect } from '@playwright/test';

const LONG_MESSAGE = 'This is a very long question to test if the input chat bubble breaks when the user types an extremely lengthy message that goes on and on without stopping. What happens to the Arizona water supply when there is a severe drought? How does the Colorado River affect our state? Can you tell me more about groundwater and aquifers? I want to understand the full picture of water management in our desert environment.';

test.describe('User Message Long Text', () => {
  test('long user message displays fully without cutoff or overflow', async ({ page }) => {
    await page.goto('/chat');
    await page.waitForLoadState('domcontentloaded');

    const textbox = page.getByLabel('Message input');
    await expect(textbox).toBeVisible();
    await textbox.fill(LONG_MESSAGE);

    await page.locator('.composer__btn-send').click();

    // Wait for user message bubble to appear
    const userBubble = page.locator('.bubble--user').last();
    await expect(userBubble).toBeVisible({ timeout: 5000 });

    // Assert full text is visible
    const content = userBubble.locator('.bubble--user__content');
    await expect(content).toContainText(
      'This is a very long question to test if the input chat bubble breaks'
    );
    await expect(content).toContainText(
      'full picture of water management in our desert environment'
    );

    // Assert no vertical cutoff
    const verticalOk = await content.evaluate((el) => {
      const tolerance = 2;
      return el.scrollHeight <= el.clientHeight + tolerance;
    });
    expect(verticalOk).toBe(true);

    // Assert no horizontal overflow
    const horizontalOk = await content.evaluate((el) => {
      const tolerance = 2;
      return el.scrollWidth <= el.clientWidth + tolerance;
    });
    expect(horizontalOk).toBe(true);

    await page.screenshot({ path: 'test-results/user-message-long-text.png' });
  });
});
