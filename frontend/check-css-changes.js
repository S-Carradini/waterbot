const { chromium } = require('playwright');
const http = require('http');

// Check if dev server is running
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
  const port = 5173;
  const url = `http://localhost:${port}`;
  
  const serverRunning = await checkServer(url);
  if (!serverRunning) {
    console.log(`❌ Dev server not running on ${url}`);
    console.log('Please start it with: npm run dev');
    process.exit(1);
  }
  
  console.log('🔍 Checking CSS changes with Playwright...\n');
  
  const browser = await chromium.launch({ headless: false });
  
  // Create context with cache disabled
  const context = await browser.newContext({
    ignoreHTTPSErrors: true,
  });
  
  // Disable cache
  await context.setExtraHTTPHeaders({
    'Cache-Control': 'no-cache, no-store, must-revalidate',
    'Pragma': 'no-cache',
    'Expires': '0'
  });
  
  const page = await context.newPage();
  
  // Add init script to clear service workers
  await page.addInitScript(() => {
    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.getRegistrations().then(registrations => {
        registrations.forEach(reg => reg.unregister());
      });
    }
  });
  
  console.log(`Navigating to ${url}...`);
  await page.goto(url, { waitUntil: 'networkidle' });
  await page.waitForTimeout(2000); // Wait for React to render
  
  // Get the container element
  const container = await page.locator('.download-transcript-container');
  const containerExists = await container.count() > 0;
  
  if (!containerExists) {
    console.log('❌ .download-transcript-container not found!');
    await browser.close();
    process.exit(1);
  }
  
  // Get computed styles
  const computedStyles = await container.evaluate((el) => {
    const computed = window.getComputedStyle(el);
    return {
      left: computed.left,
      right: computed.right,
      top: computed.top,
      bottom: computed.bottom,
      width: computed.width,
      height: computed.height,
      display: computed.display,
      flexDirection: computed.flexDirection,
      gap: computed.gap,
      margin: computed.margin,
      padding: computed.padding,
    };
  });
  
  // Get bounding box for position verification
  const containerBox = await container.boundingBox();
  
  // Get the CSS file being used
  const cssFiles = await page.evaluate(() => {
    const links = Array.from(document.querySelectorAll('link[rel="stylesheet"]'));
    return links.map(link => link.href);
  });
  
  // Check if the CSS file content matches expected values
  let cssContent = '';
  try {
    const cssResponse = await page.goto(cssFiles.find(href => href.includes('/assets/')), { waitUntil: 'networkidle' });
    cssContent = await cssResponse.text();
  } catch (e) {
    console.log('⚠️  Could not fetch CSS file content');
  }
  
  // Expected values from App.css
  const expectedLeft = '92%';
  const expectedRight = '1.43%';
  
  console.log('\n=== CSS CHANGE VERIFICATION ===\n');
  console.log('📄 Computed Styles:');
  console.log(`  left: ${computedStyles.left}`);
  console.log(`  right: ${computedStyles.right}`);
  console.log(`  top: ${computedStyles.top}`);
  console.log(`  bottom: ${computedStyles.bottom}`);
  console.log(`  width: ${computedStyles.width}`);
  console.log(`  height: ${computedStyles.height}`);
  console.log(`  gap: ${computedStyles.gap}`);
  console.log(`  display: ${computedStyles.display}`);
  console.log(`  flexDirection: ${computedStyles.flexDirection}`);
  
  console.log('\n📍 Position (Bounding Box):');
  if (containerBox) {
    console.log(`  X: ${containerBox.x.toFixed(2)}px`);
    console.log(`  Y: ${containerBox.y.toFixed(2)}px`);
    console.log(`  Width: ${containerBox.width.toFixed(2)}px`);
    console.log(`  Height: ${containerBox.height.toFixed(2)}px`);
  }
  
  console.log('\n📋 Expected Values (from App.css):');
  console.log(`  left: ${expectedLeft}`);
  console.log(`  right: ${expectedRight}`);
  
  console.log('\n✅ Verification Results:');
  const leftMatch = computedStyles.left.includes('92') || computedStyles.left.includes('1176') || computedStyles.left.includes('1177');
  const rightMatch = computedStyles.right.includes('1.43') || computedStyles.right.includes('18') || computedStyles.right.includes('19');
  
  if (leftMatch && rightMatch) {
    console.log('  ✅ CSS changes ARE being reflected!');
    console.log('  ✅ left: 92% is applied');
    console.log('  ✅ right: 1.43% is applied');
  } else {
    console.log('  ❌ CSS changes are NOT being reflected');
    if (!leftMatch) {
      console.log(`  ❌ Expected left to be ~92% but got: ${computedStyles.left}`);
    }
    if (!rightMatch) {
      console.log(`  ❌ Expected right to be ~1.43% but got: ${computedStyles.right}`);
    }
    console.log('\n🔧 Troubleshooting:');
    console.log('  1. Make sure you\'re viewing http://localhost:5173 (dev server)');
    console.log('  2. Hard reload: Ctrl+Shift+R (Windows) or Cmd+Shift+R (Mac)');
    console.log('  3. Clear browser cache');
    console.log('  4. Check DevTools Network tab for cached CSS files');
  }
  
  // Check CSS file content
  if (cssContent) {
    const hasExpectedLeft = cssContent.includes('left:92%') || cssContent.includes('left: 92%');
    const hasExpectedRight = cssContent.includes('right:1.43%') || cssContent.includes('right: 1.43%');
    
    console.log('\n📄 CSS File Content Check:');
    if (hasExpectedLeft && hasExpectedRight) {
      console.log('  ✅ CSS file contains expected values');
    } else {
      console.log('  ❌ CSS file does NOT contain expected values');
      if (!hasExpectedLeft) console.log('    Missing: left: 92%');
      if (!hasExpectedRight) console.log('    Missing: right: 1.43%');
    }
  }
  
  // Take screenshot
  const screenshotPath = 'css-verification.png';
  await page.screenshot({ path: screenshotPath, fullPage: false });
  console.log(`\n📸 Screenshot saved: ${screenshotPath}`);
  
  console.log('\nKeeping browser open for 5 seconds for manual inspection...');
  await page.waitForTimeout(5000);
  
  await browser.close();
})();

