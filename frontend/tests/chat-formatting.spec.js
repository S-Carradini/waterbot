import { test, expect } from '@playwright/test';

test.describe('Chat response formatting', () => {
  test('Next Steps response should have compact formatting', async ({ page, browserName }) => {
    test.setTimeout(180000);

    await page.goto('/chat');
    await page.waitForSelector('.composer', { timeout: 10000 });

    // Send message that triggers structured response
    await page.locator('.composer__input').fill('What are the next steps for water conservation?');
    await page.locator('.composer__btn-send').click();

    // Wait for typing indicator, then wait for it to go away
    await page.waitForSelector('.typing-indicator__dot', { timeout: 15000 });
    await page.waitForSelector('.typing-indicator__dot', { state: 'detached', timeout: 60000 });
    // Wait for chips to be stable
    await page.locator('.chip').first().waitFor({ timeout: 30000 });
    await page.waitForTimeout(2000);

    // Click "Next Steps"
    await page.locator('.chip', { hasText: /next steps/i }).click();

    // Wait for new typing indicator
    await page.waitForSelector('.typing-indicator__dot', { timeout: 15000 });
    // Wait for typing to finish
    await page.waitForSelector('.typing-indicator__dot', { state: 'detached', timeout: 60000 });
    // Wait for typewriter to finish (chips reappear)
    await page.locator('.chip').first().waitFor({ timeout: 60000 });
    await page.waitForTimeout(1000);

    // Get the last bot response
    const botTexts = page.locator('.bubble--bot__text');
    const count = await botTexts.count();
    const lastBubble = botTexts.nth(count - 1);
    const innerHTML = await lastBubble.innerHTML();

    console.log('=== RAW INNER HTML ===');
    console.log(innerHTML);
    console.log('=== END ===');

    await page.screenshot({ path: 'test-results/chat-nextsteps.png', fullPage: true });

    // No 3+ consecutive <br>
    const excessiveBrs = (innerHTML.match(/<br>\s*<br>\s*<br>/gi) || []).length;
    console.log(`Excessive <br>: ${excessiveBrs}`);
    expect(excessiveBrs).toBe(0);

    // No empty <p>
    const emptyPs = (innerHTML.match(/<p>\s*<\/p>/gi) || []).length;
    console.log(`Empty <p>: ${emptyPs}`);
    expect(emptyPs).toBe(0);

    // Dash items should be in <li>, not loose <p>-text
    const looseDashItems = (innerHTML.match(/<p>\s*-\s*[A-Za-z]/g) || []).length;
    console.log(`Loose dash items: ${looseDashItems}`);
    expect(looseDashItems).toBe(0);
  });
});
