import { test, expect } from '@playwright/test';

test.describe('Microphone Button Animation', () => {
  test.beforeEach(async ({ page, context }) => {
    // Mock Speech Recognition API
    await context.addInitScript(() => {
      // Create a mock SpeechRecognition class
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
          // Simulate a result after a short delay
          setTimeout(() => {
            if (this.onresult) {
              const mockEvent = {
                resultIndex: 0,
                results: [{
                  0: { transcript: 'test' },
                  isFinal: true
                }]
              };
              this.onresult(mockEvent);
            }
          }, 100);
        }
        
        stop() {
          if (this.onend) this.onend();
        }
      }
      
      // Add to window
      window.SpeechRecognition = MockSpeechRecognition;
      window.webkitSpeechRecognition = MockSpeechRecognition;
    });

    // Navigate to the app (adjust URL based on your routing)
    await page.goto('/waterbot');
    // Wait for the page to load
    await page.waitForLoadState('domcontentloaded');
    // Wait for React to render and Speech Recognition to initialize
    await page.waitForSelector('button.mic-icon-button', { timeout: 10000 });
    // Wait a bit more for Speech Recognition to be initialized
    await page.waitForTimeout(500);
  });

  test('should show recording modal with pulsing rings animation when record button is clicked', async ({ page }) => {
    // Find the microphone button
    const micButton = page.locator('button.mic-icon-button');
    await expect(micButton).toBeVisible();

    // Check initial state - button should not have recording class
    await expect(micButton).not.toHaveClass(/recording/);

    // Check that recording modal is not visible initially
    const recordingModal = page.locator('.recording-modal-overlay');
    await expect(recordingModal).not.toBeVisible();

    // Simulate recording state by triggering React state
    await page.evaluate(() => {
      // Find React component and trigger state update
      const button = document.querySelector('button.mic-icon-button');
      if (button) {
        // Trigger click to start recording (if Speech Recognition is mocked)
        button.click();
      }
    });

    await page.waitForTimeout(300);

    // Verify the button now has the recording class
    await expect(micButton).toHaveClass(/recording/);

    // Verify the recording modal is visible
    await expect(recordingModal).toBeVisible();

    // Verify modal content is present
    const modalContent = page.locator('.recording-modal-content');
    await expect(modalContent).toBeVisible();

    // Verify that all four pulse rings are present in the modal
    const ring1 = page.locator('.recording-modal-ring.ring-1');
    const ring2 = page.locator('.recording-modal-ring.ring-2');
    const ring3 = page.locator('.recording-modal-ring.ring-3');
    const ring4 = page.locator('.recording-modal-ring.ring-4');

    await expect(ring1).toBeVisible();
    await expect(ring2).toBeVisible();
    await expect(ring3).toBeVisible();
    await expect(ring4).toBeVisible();

    // Verify the rings have the correct CSS properties for animation
    const ring1Style = await ring1.evaluate((el) => {
      const computed = window.getComputedStyle(el);
      return {
        position: computed.position,
        borderRadius: computed.borderRadius,
        border: computed.border,
      };
    });

    expect(ring1Style.position).toBe('absolute');
    expect(ring1Style.borderRadius).toBe('50%');
    // Border can be in rgba or rgb format
    expect(ring1Style.border).toMatch(/rgba?\(140,\s*29,\s*64/);

    // Verify the modal text is present
    const modalText = page.locator('.recording-modal-text');
    await expect(modalText).toBeVisible();
    await expect(modalText).toHaveText('Recording...');

    // Verify the stop button is present
    const stopButton = page.locator('.recording-modal-close');
    await expect(stopButton).toBeVisible();
    await expect(stopButton).toHaveText('Stop Recording');
  });

  test('should stop animation when recording modal is closed', async ({ page }) => {
    const micButton = page.locator('button.mic-icon-button');
    const recordingModal = page.locator('.recording-modal-overlay');

    // Simulate starting recording
    await page.evaluate(() => {
      const button = document.querySelector('button.mic-icon-button');
      if (button) {
        button.click();
      }
    });
    await page.waitForTimeout(300);

    // Verify recording is active
    await expect(micButton).toHaveClass(/recording/);
    await expect(recordingModal).toBeVisible();

    // Click the stop button in the modal
    const stopButton = page.locator('.recording-modal-close');
    await stopButton.click();
    await page.waitForTimeout(200);

    // Verify recording is stopped
    await expect(micButton).not.toHaveClass(/recording/);
    await expect(recordingModal).not.toBeVisible();

    // Verify the microphone icon color returns to original
    const micIcon = micButton.locator('i.fa-microphone');
    const iconColor = await micIcon.evaluate((el) => {
      return window.getComputedStyle(el).color;
    });
    expect(iconColor).toBe('rgb(140, 29, 64)'); // #8c1d40

    // Verify the button background returns to white
    const buttonBg = await micButton.evaluate((el) => {
      return window.getComputedStyle(el).backgroundColor;
    });
    expect(buttonBg).toBe('rgb(255, 255, 255)'); // white
  });

  test('should have correct animation keyframes for pulsing rings in modal', async ({ page }) => {
    const micButton = page.locator('button.mic-icon-button');
    
    // Simulate recording state to show modal
    await page.evaluate(() => {
      const button = document.querySelector('button.mic-icon-button');
      if (button) {
        button.click();
      }
    });
    await page.waitForTimeout(300);

    // Check that animations are defined in the stylesheet
    const hasAnimation = await page.evaluate(() => {
      const styleSheets = Array.from(document.styleSheets);
      for (const sheet of styleSheets) {
        try {
          const rules = Array.from(sheet.cssRules || []);
          for (const rule of rules) {
            if (rule instanceof CSSKeyframesRule) {
              if (
                rule.name === 'recordingModalRing1' ||
                rule.name === 'recordingModalRing2' ||
                rule.name === 'recordingModalRing3' ||
                rule.name === 'recordingModalRing4'
              ) {
                return true;
              }
            }
          }
        } catch (e) {
          // Cross-origin stylesheets may throw
          continue;
        }
      }
      return false;
    });

    expect(hasAnimation).toBe(true);

    // Verify ring animations have delays
    const ring2 = page.locator('.recording-modal-ring.ring-2');
    const ring2Animation = await ring2.evaluate((el) => {
      return window.getComputedStyle(el).animationDelay;
    });
    expect(ring2Animation).toBe('0.3s');

    const ring3 = page.locator('.recording-modal-ring.ring-3');
    const ring3Animation = await ring3.evaluate((el) => {
      return window.getComputedStyle(el).animationDelay;
    });
    expect(ring3Animation).toBe('0.6s');

    const ring4 = page.locator('.recording-modal-ring.ring-4');
    const ring4Animation = await ring4.evaluate((el) => {
      return window.getComputedStyle(el).animationDelay;
    });
    expect(ring4Animation).toBe('0.9s');
  });
});
