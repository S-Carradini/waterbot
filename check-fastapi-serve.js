const { chromium } = require('playwright');
const http = require('http');

function checkServer(url) {
  return new Promise((resolve) => {
    const req = http.get(url, () => {
      resolve(true);
    });
    req.on('error', () => {
      resolve(false);
    });
    req.setTimeout(1000, () => {
      req.destroy();
      resolve(false);
    });
  });
}

(async () => {
  const ports = [8000, 8010];
  let serverUrl = null;
  
  for (const port of ports) {
    const url = `http://localhost:${port}`;
    if (await checkServer(url)) {
      serverUrl = url;
      console.log(`✅ Found FastAPI server on port ${port}`);
      break;
    }
  }
  
  if (!serverUrl) {
    console.log('❌ FastAPI server not running on ports 8000 or 8010');
    process.exit(1);
  }
  
  const browser = await chromium.launch({ headless: false });
  const context = await browser.newContext();
  const page = await context.newPage();
  
  // Disable cache
  await context.setExtraHTTPHeaders({
    'Cache-Control': 'no-cache, no-store, must-revalidate',
    'Pragma': 'no-cache',
    'Expires': '0'
  });
  
  console.log(`\n🔍 Checking what FastAPI is serving from ${serverUrl}...\n`);
  
  await page.goto(serverUrl, { waitUntil: 'networkidle' });
  await page.waitForTimeout(2000);
  
  // Check if the container exists and get its styles
  const container = await page.locator('.download-transcript-container');
  const containerExists = await container.count() > 0;
  
  if (!containerExists) {
    console.log('❌ .download-transcript-container not found!');
    await browser.close();
    process.exit(1);
  }
  
  const containerStyles = await container.evaluate((el) => {
    const computed = window.getComputedStyle(el);
    return {
      left: computed.left,
      right: computed.right,
      top: computed.top,
    };
  });
  
  const containerBox = await container.boundingBox();
  
  // Check the CSS file being served
  const cssUrl = await page.evaluate(() => {
    const links = Array.from(document.querySelectorAll('link[rel="stylesheet"]'));
    const cssLink = links.find(link => link.href.includes('/assets/'));
    return cssLink ? cssLink.href : null;
  });
  
  console.log('=== FASTAPI SERVED CONTENT ===\n');
  console.log('📄 Container Styles:');
  console.log(`  left: ${containerStyles.left}`);
  console.log(`  right: ${containerStyles.right}`);
  console.log(`  top: ${containerStyles.top}`);
  
  if (containerBox) {
    console.log(`\n📍 Position:`);
    console.log(`  X: ${containerBox.x.toFixed(2)}px`);
    console.log(`  Y: ${containerBox.y.toFixed(2)}px`);
  }
  
  console.log(`\n📁 CSS File: ${cssUrl || 'Not found'}`);
  
  // Check if the changes are reflected
  const expectedRight = 'calc(10.28% - 205px)';
  const hasExpectedRight = containerStyles.right.includes('calc') || 
                          containerStyles.right.includes('-205') ||
                          containerStyles.right.includes('-205px');
  
  console.log('\n=== VERIFICATION ===');
  if (hasExpectedRight || (parseFloat(containerStyles.right) < 0 && containerStyles.right.includes('-'))) {
    console.log('✅ Latest CSS changes ARE being served by FastAPI');
  } else {
    console.log('❌ FastAPI is serving OLD CSS (right should be calc(10.28% - 205px))');
    console.log(`   Current right value: ${containerStyles.right}`);
    console.log('\n💡 Solution: Restart FastAPI server');
  }
  
  // Check for the rogue "0" issue
  const actionsRow = await page.locator('.actions-row');
  const actionsRowExists = await actionsRow.count() > 0;
  
  if (actionsRowExists) {
    const actionsRowText = await actionsRow.first().textContent();
    if (actionsRowText.includes('0Tell Me More') || actionsRowText.trim().startsWith('0')) {
      console.log('\n❌ Rogue "0" issue still present in FastAPI served content');
    } else {
      console.log('\n✅ Rogue "0" issue is fixed');
    }
  }
  
  const screenshotPath = 'fastapi-verification.png';
  await page.screenshot({ path: screenshotPath, fullPage: false });
  console.log(`\n📸 Screenshot saved: ${screenshotPath}`);
  
  await page.waitForTimeout(2000);
  await browser.close();
})();

